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

import pytest
from wiki_harness import PwbHarness, WikiApi

from wtbot.settings import WikiSettings
from wtbot.wiki.client import PywikibotClient
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

    requests = len(recent_exchanges())
    assert pages_fetched > 1, "the fan-out fetched nothing to measure"
    per_page = requests / pages_fetched
    assert per_page <= PER_PAGE_BUDGET_AMORTISED, (
        f"{requests} upstream requests for {pages_fetched} pages "
        f"({per_page:.2f}/page) exceeds the {PER_PAGE_BUDGET_AMORTISED}/page "
        "budget -- at the configured throttle that is proportionally longer to "
        "fetch a book and proportionally more of the rate-limit allowance"
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

    expected = {upstream_pwb.endpoint.api_url.split("/")[2]}
    hosts = {exchange.host for exchange in recent_exchanges()}
    assert hosts <= expected, f"a fan-out reached hosts nobody asked for: {hosts}"


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
