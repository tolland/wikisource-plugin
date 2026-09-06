"""What a fetch costs upstream, per page.

Rate limiting is a budget problem, and a budget needs a measurement. The
throttle (``WikiSettings.read_throttle``) fixes requests per minute; this fixes
requests per *page*; the wiki sees the product. So the per-page cost is not a
detail -- doubling it is a rate limit exceeded just as surely as halving the
throttle.

Two instruments, because the question has two halves:

- Does our code ask for the minimum? Guarded offline against a spy that charges
  for the loads pywikibot charges for. Runs everywhere, every time.
- What does a whole fan-out really cost, including the requests pywikibot makes
  on its own behalf? Measured over docker against a real wiki, counted by the
  same HTTP tap that diagnoses rate limiting in production.

The measurement used to come from a vcrpy cassette. A recording cannot show the
effect of a fix made after it was recorded, and this repository's cassettes had
also drifted out of date against pywikibot -- so the number they gave was both
stale and unfalsifiable. The docker harness is a wiki, and answers now.
"""

from collections import Counter
from urllib.parse import urlsplit

import pytest
from wiki_harness import PwbHarness, WikiApi

from wtbot.model import Page
from wtbot.settings import WikiSettings
from wtbot.wiki.client import FakeWikiClient, PywikibotClient
from wtbot.wiki.http_tap import clear_exchanges, install_http_tap, recent_exchanges
from wtbot.wiki.wiki_types import PageNotFound

#: Upstream requests per page a fetch may cost. A page's body has to be asked
#: for, so one is the floor; this leaves no room for a second per-page call.
PER_PAGE_BUDGET = 1

#: The same budget for a whole fan-out, where per-page cost is amortised with
#: the fixed ones (site detection, siteinfo, paraminfo, userinfo, the File:
#: lookup and download). Above one, but nowhere near the two that an existence
#: check per page used to add.
PER_PAGE_BUDGET_AMORTISED = 1.6


#: One wiki can appear under several loopback spellings: the API endpoint is
#: configured as 127.0.0.1 while MediaWiki's $wgServer says localhost, so file
#: URLs come back with the other name.
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


def _hostname(host: str) -> str:
    return host.rsplit(":", 1)[0] if ":" in host else host


def _port(host: str) -> int | None:
    _, sep, port = host.rpartition(":")
    return int(port) if sep and port.isdigit() else None


def _breakdown(exchanges) -> str:
    """What the requests were, so a budget failure diagnoses itself rather
    than leaving someone to re-run it under a debugger."""
    counts = Counter(e.query_summary or e.path for e in exchanges)
    lines = [f"  {n:4d}  {what}" for what, n in counts.most_common()]
    return "requests by kind:\n" + "\n".join(lines)


def test_the_configured_throttle_stays_inside_the_authenticated_allowance():
    """Wikimedia grants 200 req/min to an authenticated account with few
    edits; the throttle is what keeps us under it."""
    settings = WikiSettings(family="wikisource", code="en")
    assert 60 / settings.read_throttle <= 200


@pytest.mark.slow
def test_a_real_fan_out_stays_inside_its_per_page_budget(
    engine, tmp_path, seeded_upstream: WikiApi, upstream_pwb: PwbHarness
):
    """The measurement, over docker: fetch a book, count what went out.

    Counted through ``http_tap``, which watches pywikibot's own session -- so
    this sees the requests pywikibot makes for its own reasons, which are
    exactly the ones easy to forget when reasoning about a budget.
    """
    from conftest import CANADIAN_PATENT_INDEX, drain, register_site
    from fastapi.testclient import TestClient
    from sqlmodel import Session, select

    from wtbot.main import create_app
    from wtbot.model import Page

    install_http_tap(maxlen=8192)
    clear_exchanges()

    app = create_app(
        engine=engine,
        client_factory=lambda site: upstream_pwb.client,
        blob_root=tmp_path / "blobs",
    )
    with TestClient(app) as http:
        register_site(http, label="harness-upstream", family="mywikisource", code="en")
        http.post(
            "/fetch/",
            json={
                "title": CANADIAN_PATENT_INDEX,
                "label": "harness-upstream",
                "depth": 1,
            },
        )
        drain(http)

    with Session(engine) as session:
        pages_fetched = len(session.exec(select(Page)).all())

    exchanges = recent_exchanges()
    assert pages_fetched > 1, "the fan-out fetched nothing to measure"

    # The sharp claim first: one body load per page, and no more. This is the
    # part under our control, and it is what regressed before -- the amortised
    # ratio below also moves with fixed costs, which it should not be blamed
    # for.
    body_loads = [e for e in exchanges if "revisions" in e.query_summary]
    assert len(body_loads) <= pages_fetched, (
        f"{len(body_loads)} body loads for {pages_fetched} pages -- a page is "
        "being asked for more than once"
    )

    per_page = len(exchanges) / pages_fetched
    assert per_page <= PER_PAGE_BUDGET_AMORTISED, (
        f"{len(exchanges)} upstream requests for {pages_fetched} pages "
        f"({per_page:.2f}/page) exceeds the {PER_PAGE_BUDGET_AMORTISED}/page "
        "budget -- at the configured throttle that is proportionally longer to "
        "fetch a book and proportionally more of the rate-limit allowance.\n"
        + _breakdown(exchanges)
    )


@pytest.mark.slow
def test_a_fan_out_talks_only_to_the_wiki_it_was_asked_about(
    engine, tmp_path, seeded_upstream: WikiApi, upstream_pwb: PwbHarness
):
    """Which hosts a fetch reaches is part of the budget.

    On en.wikisource a fan-out also reaches Commons, because the scan lives
    there -- legitimate, but worth knowing rather than discovering. The harness
    wiki hosts its own scan, so anything beyond it is traffic nobody asked for.
    """
    from conftest import CANADIAN_PATENT_INDEX, drain, register_site
    from fastapi.testclient import TestClient

    from wtbot.main import create_app

    install_http_tap(maxlen=8192)
    clear_exchanges()

    app = create_app(
        engine=engine,
        client_factory=lambda site: upstream_pwb.client,
        blob_root=tmp_path / "blobs",
    )
    with TestClient(app) as http:
        register_site(http, label="harness-upstream", family="mywikisource", code="en")
        http.post(
            "/fetch/",
            json={
                "title": CANADIAN_PATENT_INDEX,
                "label": "harness-upstream",
                "depth": 1,
            },
        )
        drain(http)

    # One wiki, spelled more than one way: MediaWiki serves file URLs from
    # $wgServer, which the harness sets to localhost while the API endpoint is
    # 127.0.0.1. Same host, same port, same wiki -- comparing the strings
    # would fail on the spelling and say nothing about traffic.
    expected_port = urlsplit(upstream_pwb.endpoint.api_url).port
    hosts = {exchange.host for exchange in recent_exchanges()}
    elsewhere = {
        host
        for host in hosts
        if _hostname(host) not in _LOOPBACK or _port(host) != expected_port
    }
    assert not elsewhere, (
        f"a fan-out reached hosts nobody asked for: {sorted(elsewhere)} "
        f"(the wiki under test is loopback:{expected_port})"
    )


class _CountingImageClient(FakeWikiClient):
    """Counts how the scan-image enrichment was asked for -- one call per
    page, or one call for all of them."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.single_calls: list[str] = []
        self.bulk_calls: list[list[str]] = []

    def get_page_images(self, title):
        self.single_calls.append(title)
        return super().get_page_images(title)

    def get_page_images_bulk(self, titles):
        self.bulk_calls.append(list(titles))
        return super().get_page_images_bulk(titles)


def test_a_fan_out_asks_for_its_pages_images_once_not_once_per_page(engine, tmp_path):
    """The second per-page request, removed.

    Measured over docker, a 25-page fan-out cost 60 requests -- 2.4 per page,
    where the body needs one. The other was ``prop=imageforpage``, asked per
    child. It is a pageset module, so the fan-out (which knows every child
    title before any child is fetched) asks once for fifty.
    """
    from sqlmodel import Session, select

    from wtbot.fetch.queue_runner import drain_queue
    from wtbot.model import FetchRequest, Site
    from wtbot.wiki.wiki_types import RemotePage, RemotePageImages

    index_title = "Index:Budget.djvu"
    page_titles = [f"Page:Budget.djvu/{n}" for n in range(1, 6)]
    pages = {
        index_title: RemotePage(
            title=index_title,
            namespace_key=252,
            namespace_canonical="Index",
            content_model="proofread-index",
            text='<pagelist 1to5="1" />',
            revid=1,
            page_count=5,
        )
    }
    pages.update(
        {
            title: RemotePage(
                title=title,
                namespace_key=250,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="body",
                revid=1,
            )
            for title in page_titles
        }
    )
    images = {
        title: RemotePageImages(thumbnail_url=f"https://wiki.test/{title}.jpg")
        for title in page_titles
    }
    wiki = _CountingImageClient(
        pages=pages, files={"File:Budget.djvu": b"scan"}, page_images=images
    )

    with Session(engine) as session:
        site = Site(family="mywikisource", code="en", label="budget")
        session.add(site)
        session.commit()
        session.refresh(site)
        session.add(FetchRequest(site_pk=site.pk, title=index_title, depth=1))
        session.commit()

        drain_queue(session, lambda _site: wiki, blob_root=tmp_path / "blobs", batch=1)

        fetched = {p.title for p in session.exec(select(Page)).all()}

    assert set(page_titles) <= fetched, "the fan-out did not fetch its children"
    assert wiki.bulk_calls == [page_titles], "children should be asked for in one go"
    assert wiki.single_calls == [], (
        "every child asked for its own image despite the bulk prefetch: "
        f"{wiki.single_calls}"
    )


def test_a_page_fetched_on_its_own_still_gets_its_image(engine, tmp_path):
    """The fallback. A child drained in a later run than its fan-out has no
    prefetched entry, and must still end up with its thumbnail."""
    from sqlmodel import Session

    from wtbot.fetch.queue_runner import drain_queue
    from wtbot.model import FetchRequest, Site
    from wtbot.wiki.wiki_types import RemotePage, RemotePageImages

    title = "Page:Budget.djvu/1"
    wiki = _CountingImageClient(
        pages={
            title: RemotePage(
                title=title,
                namespace_key=250,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="body",
                revid=1,
            )
        },
        page_images={title: RemotePageImages(thumbnail_url="https://wiki.test/1.jpg")},
    )

    with Session(engine) as session:
        site = Site(family="mywikisource", code="en", label="budget")
        session.add(site)
        session.commit()
        session.refresh(site)
        session.add(FetchRequest(site_pk=site.pk, title=title))
        session.commit()

        drain_queue(session, lambda _site: wiki, blob_root=tmp_path / "blobs")

    assert wiki.single_calls == [title]


# -- the guard -------------------------------------------------------------


class _Namespace:
    id = 104
    canonical_name = "Page"


class _Revision:
    revid = 42
    parentid = 41
    timestamp = None
    user = "someone"
    comment = "c"
    sha1 = "a" * 40
    size = 10
    text = "the body"


class _SpyPage:
    """Charges for loads the way pywikibot charges for them.

    ``exists()`` reads ``pageid``, which triggers ``loadpageinfo`` (prop=info)
    when cold. ``latest_revision`` triggers a revisions load whose response
    also carries prop=info -- so it answers existence, content model and body
    together. Anything already loaded is free, which is the whole point: the
    order these are touched in decides whether a page costs one request or two.
    """

    def __init__(self, title: str, loads: list[str], *, missing: bool = False):
        self._title = title
        self._loads = loads
        self._missing = missing
        self._loaded = False

    def _load_info(self) -> None:
        if not self._loaded:
            self._loads.append("info")
            self._loaded = True

    def _load_revisions(self) -> None:
        if not self._loaded:
            self._loads.append("info|revisions")
            self._loaded = True

    def exists(self) -> bool:
        self._load_info()
        return not self._missing

    @property
    def latest_revision(self) -> _Revision:
        self._load_revisions()
        if self._missing:
            raise _FakeNoPageError(self._title)
        return _Revision()

    @property
    def text(self) -> str:
        self._load_revisions()
        return _Revision.text

    @property
    def content_model(self) -> str:
        self._load_info()
        return "proofread-page"

    @property
    def pageid(self) -> int:
        self._load_info()
        return 7

    def namespace(self) -> _Namespace:
        return _Namespace()

    def title(self) -> str:
        return self._title


class _FakeNoPageError(Exception):
    pass


class _FakeInvalidPageError(Exception):
    pass


class _FakeExceptions:
    NoPageError = _FakeNoPageError
    InvalidPageError = _FakeInvalidPageError


class _FakePwb:
    exceptions = _FakeExceptions

    def __init__(self, loads: list[str], *, missing: bool = False):
        self._loads = loads
        self._missing = missing

    def Page(self, site, title):  # noqa: N802 - mirrors pywikibot's name
        return _SpyPage(title, self._loads, missing=self._missing)


def _client(loads: list[str], *, missing: bool = False) -> PywikibotClient:
    """A PywikibotClient with the pywikibot module swapped for the spy.

    Built without __init__ deliberately: constructing one for real detects the
    site and logs in over the network, and none of that is what this measures.
    """
    client = PywikibotClient.__new__(PywikibotClient)
    client.settings = WikiSettings(family="wikisource", code="en")
    client._pwb = _FakePwb(loads, missing=missing)
    client.site = object()
    return client


def test_fetching_one_page_costs_one_request():
    """The regression guard for the whole rate-limit effort. It used to cost
    two: an existence check, then a body load that establishes existence
    anyway -- doubling the cost of every page of every book."""
    loads: list[str] = []
    remote = _client(loads).get_page("Page:Book.pdf/7")

    assert len(loads) == PER_PAGE_BUDGET, f"expected one load, got {loads}"
    assert loads == ["info|revisions"]
    assert remote.text == "the body"
    assert remote.content_model == "proofread-page"
    assert remote.revid == 42


def test_a_missing_page_also_costs_one_request():
    """The not-found path must not pay for a separate existence check either:
    a refresh over a partially transcribed index asks for pages that do not
    exist yet, and those are the common case, not the exception."""
    loads: list[str] = []
    with pytest.raises(PageNotFound):
        _client(loads, missing=True).get_page("Page:Book.pdf/999")

    assert len(loads) == PER_PAGE_BUDGET, f"expected one load, got {loads}"


def test_one_wiki_spelled_two_ways_is_still_one_wiki():
    """Why the host check compares loopback+port rather than strings.

    The harness serves its API on 127.0.0.1 and its file URLs on localhost
    (MediaWiki's $wgServer), so a literal comparison fails on the spelling and
    reports traffic that never left the machine.
    """
    assert _hostname("localhost:18581") == "localhost"
    assert _port("localhost:18581") == 18581
    assert {_hostname(h) for h in ("localhost:18581", "127.0.0.1:18581")} <= _LOOPBACK


def test_a_third_party_wiki_is_not_mistaken_for_the_one_under_test():
    """...and the check still catches what it is for: Commons, Wikidata, or
    anything else a fetch reached without being asked to."""
    assert _hostname("commons.wikimedia.org") not in _LOOPBACK
    assert _port("commons.wikimedia.org") is None
    # Same host name, different wiki: the harness pair differs only by port.
    assert _port("127.0.0.1:18582") != 18581


def test_the_breakdown_names_the_requests_that_blew_the_budget():
    """A budget failure has to say what the requests were; the number alone
    sends someone back to a debugger, which is where this one came from."""
    from wtbot.wiki.http_tap import HttpExchange

    exchanges = [
        HttpExchange(
            "GET", "w", "/api.php", 200, "action=query prop=revisions", 0.1, None, 0.0
        ),
        HttpExchange(
            "GET", "w", "/api.php", 200, "action=query prop=revisions", 0.1, None, 1.0
        ),
        HttpExchange(
            "GET",
            "w",
            "/api.php",
            200,
            "action=query prop=imageforpage",
            0.1,
            None,
            2.0,
        ),
    ]

    report = _breakdown(exchanges)

    assert "prop=revisions" in report
    assert "2" in report.split("prop=revisions")[0].split("\n")[-1]
    assert "prop=imageforpage" in report


def test_the_image_query_sends_only_parameters_the_module_accepts():
    """ProofreadPage's imageforpage module takes exactly one parameter, `prop`.

    We used to also send `prppifpsize`, hoping for a 240px rendition. No such
    parameter exists, so every request came back with "Unrecognized parameter:
    prppifpsize" -- a warning, not an error, on a response that still parsed,
    which is why it survived so long. The thumbnail width is the extension's
    to choose.
    """
    from wtbot.wiki.client import IMAGE_FOR_PAGE_PROPS, PywikibotClient

    sent: list[dict] = []

    client = PywikibotClient.__new__(PywikibotClient)
    client.site = object()
    client._api_query = lambda **params: sent.append(params) or None

    client.get_page_images("Page:Book.djvu/1")
    client.get_page_images_bulk(["Page:Book.djvu/1", "Page:Book.djvu/2"])

    assert sent, "no query was made"
    for params in sent:
        assert "prppifpsize" not in params
        assert params["prppifpprop"] == IMAGE_FOR_PAGE_PROPS
        # `prop` is the module's whole parameter surface; anything else with
        # its prefix is a parameter it does not have.
        assert [k for k in params if k.startswith("prppifp")] == ["prppifpprop"]


def test_the_bulk_image_query_chunks_to_the_pageset_limit():
    """Fifty titles per request: MediaWiki's pageset cap without
    apihighlimits, which an ordinary account does not have."""
    from wtbot.wiki.client import PywikibotClient

    sent: list[dict] = []
    client = PywikibotClient.__new__(PywikibotClient)
    client.site = object()
    client._api_query = lambda **params: sent.append(params) or None

    client.get_page_images_bulk([f"Page:Book.djvu/{n}" for n in range(1, 121)])

    assert len(sent) == 3  # 50 + 50 + 20
    assert len(sent[0]["titles"].split("|")) == 50
    assert len(sent[-1]["titles"].split("|")) == 20
