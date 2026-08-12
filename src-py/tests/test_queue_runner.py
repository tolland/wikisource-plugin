import pytest
from conftest import credential_for, drain
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.main import create_app
from wtbot.model import FetchKind, FetchRequest, FetchStatus, Page, Site
from wtbot.queue_runner import DrainStop, drain_queue, pending_count, queue_stats
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemotePage

"""Draining the fetch queue, as a separate operation from enqueueing it.

The split exists because fetching is slow on purpose: every wiki call is
throttled to stay inside the rate limit, so a book's worth of pages cannot be
something an enqueue call waits for. What these tests pin is that the drain is
a *loop* (a fan-out enqueues children after the first pass began), that it says
so honestly when it stops early, and that enqueueing on its own fetches
nothing.
"""

LABEL = "test"
_INDEX = "Index:Queue.djvu"


def _page(
    title: str,
    model: str = "proofread-page",
    ns: str = "Page",
    *,
    revid: int,
) -> RemotePage:
    return RemotePage(
        title=title,
        namespace_key=250,
        namespace_canonical=ns,
        content_model=model,
        text=f"body of {title}",
        revid=revid,
    )


def _index_remote(page_count: int) -> RemotePage:
    pagelist = f'<pagelist 1to{page_count}="1" />'
    return RemotePage(
        title=_INDEX,
        namespace_key=252,
        namespace_canonical="Index",
        content_model="proofread-index",
        text=f"{{{{:MediaWiki:Proofreadpage_index_template}}}}{pagelist}",
        revid=1,
        page_count=page_count,
    )


@pytest.fixture
def seeded(engine):
    """A site with an Index whose fan-out has three children."""
    pages = {_INDEX: _index_remote(3)}
    pages.update(
        {
            f"Page:Queue.djvu/{n}": _page(
                f"Page:Queue.djvu/{n}",
                revid=n + 1,
            )
            for n in (1, 2, 3)
        }
    )
    wiki = FakeWikiClient(pages=pages)
    with Session(engine) as session:
        site = Site(family="mywikisource", code="en", label=LABEL)
        session.add(site)
        session.commit()
        session.refresh(site)
        credential_for(session, site)
        site_pk = site.pk
    return wiki, site_pk


def _enqueue(engine, site_pk: int, title: str, *, depth: int = 0) -> None:
    with Session(engine) as session:
        session.add(
            FetchRequest(
                site_pk=site_pk, title=title, kind=FetchKind.single, depth=depth
            )
        )
        session.commit()


def test_drain_reports_what_it_did(engine, seeded):
    wiki, site_pk = seeded
    _enqueue(engine, site_pk, _INDEX)

    with Session(engine) as session:
        result = drain_queue(session, lambda _site: wiki)

    assert result.handled == 1
    assert result.remaining == 0
    assert result.stop_reason is DrainStop.queue_empty
    assert result.complete


def test_drain_keeps_going_after_a_fan_out_enqueues_children(engine, seeded, tmp_path):
    """One pass is never enough: the children did not exist when it started."""
    wiki, site_pk = seeded
    _enqueue(engine, site_pk, _INDEX, depth=1)

    with Session(engine) as session:
        result = drain_queue(
            session, lambda _site: wiki, blob_root=tmp_path / "blobs", batch=1
        )

    assert result.handled == 4  # the index plus three children
    assert result.complete
    assert result.passes > 1

    with Session(engine) as session:
        assert len(session.exec(select(Page)).all()) == 4


def test_drain_stops_at_max_passes_and_says_the_queue_is_not_empty(engine, seeded):
    """Stopping early must never look like finishing: a caller that reads
    `complete` wrongly here stops watching a half-fetched book."""
    wiki, site_pk = seeded
    for n in (1, 2, 3):
        _enqueue(engine, site_pk, f"Page:Queue.djvu/{n}")

    with Session(engine) as session:
        result = drain_queue(session, lambda _site: wiki, batch=1, max_passes=2)

    assert result.handled == 2
    assert result.remaining == 1
    assert result.stop_reason is DrainStop.max_passes
    assert not result.complete


def test_drain_of_an_empty_queue_is_a_no_op(engine, seeded):
    wiki, _ = seeded
    with Session(engine) as session:
        result = drain_queue(session, lambda _site: wiki)
    assert result == result.__class__(
        handled=0, passes=1, remaining=0, stop_reason=DrainStop.queue_empty
    )


class _RateLimitedClient(FakeWikiClient):
    """Refuses like a rate-limited wiki: the first call succeeds, then every
    call raises with a Retry-After, which is how a limit actually arrives --
    part way through a batch, not before it."""

    def __init__(self, *args, allow: int = 1, **kwargs):
        super().__init__(*args, **kwargs)
        self._allow = allow
        self.calls = 0

    def get_page(self, title):
        self.calls += 1
        if self.calls > self._allow:
            raise _TooManyRequests()
        return super().get_page(title)


class _Response:
    status_code = 429
    headers = {"retry-after": "45"}


class _TooManyRequests(Exception):
    def __init__(self):
        super().__init__("429 Too Many Requests")
        self.response = _Response()


def test_a_drain_stops_when_the_wiki_rate_limits_us(engine, seeded):
    """The reaction that matters. A 429 means we are going too fast, so
    continuing through the queue turns one refusal into hundreds -- and
    retrying is not a fix either, since the throttle is what is wrong."""
    _, site_pk = seeded
    pages = {
        f"Page:Queue.djvu/{n}": _page(
            f"Page:Queue.djvu/{n}",
            revid=n + 1,
        )
        for n in (1, 2, 3)
    }
    wiki = _RateLimitedClient(pages=pages, allow=1)
    for n in (1, 2, 3):
        _enqueue(engine, site_pk, f"Page:Queue.djvu/{n}")

    with Session(engine) as session:
        result = drain_queue(session, lambda _site: wiki, batch=1)

    assert result.stop_reason is DrainStop.rate_limited
    assert not result.complete
    assert result.retry_after == 45.0  # parsed from the Retry-After header
    # The refusal stopped the drain rather than being spent on every request:
    # two calls (one ok, one refused), not one per queued page.
    assert wiki.calls == 2
    assert result.remaining >= 1


def test_the_rate_limited_stop_reaches_the_drain_endpoint(engine, seeded):
    _, site_pk = seeded
    pages = {
        f"Page:Queue.djvu/{n}": _page(f"Page:Queue.djvu/{n}", revid=n + 1)
        for n in (1, 2)
    }
    wiki = _RateLimitedClient(pages=pages, allow=0)
    app = create_app(engine=engine, client_factory=lambda site: wiki)
    with TestClient(app) as c:
        c.post("/fetch/", json={"title": "Page:Queue.djvu/1", "label": LABEL})
        report = drain(c)

    assert report["stop_reason"] == DrainStop.rate_limited.value
    assert report["complete"] is False
    assert report["retry_after"] == 45.0


def test_an_ordinary_failure_does_not_stop_the_drain(engine, seeded):
    """Only rate limiting stops it. A missing page is one request's problem,
    and halting the queue over one would strand every other page of a book."""
    wiki, site_pk = seeded
    _enqueue(engine, site_pk, "Page:Missing.djvu/1")
    _enqueue(engine, site_pk, _INDEX)

    with Session(engine) as session:
        result = drain_queue(session, lambda _site: wiki, batch=1)

    assert result.handled == 2
    assert result.stop_reason is DrainStop.queue_empty
    assert result.complete


def test_pending_count_includes_in_progress(engine, seeded):
    """A row left in_progress by a crashed run is unfinished work. Counting
    only `pending` would report an interrupted drain as a finished one."""
    _, site_pk = seeded
    _enqueue(engine, site_pk, _INDEX)
    with Session(engine) as session:
        stranded = session.exec(select(FetchRequest)).one()
        stranded.status = FetchStatus.in_progress
        session.add(stranded)
        session.commit()
        assert pending_count(session) == 1


def test_queue_stats_counts_by_status(engine, seeded):
    wiki, site_pk = seeded
    _enqueue(engine, site_pk, _INDEX)
    _enqueue(engine, site_pk, "Page:Missing.djvu/9")

    with Session(engine) as session:
        stats = queue_stats(session)
        assert stats.pending == 2
        assert stats.oldest_pending_at is not None

        drain_queue(session, lambda _site: wiki)
        stats = queue_stats(session)

    assert stats.counts[FetchStatus.done] == 1
    assert stats.counts[FetchStatus.error] == 1  # the title that does not exist
    assert stats.pending == 0
    assert stats.oldest_pending_at is None


# -- the HTTP surface ------------------------------------------------------


@pytest.fixture
def http(engine, seeded):
    wiki, _ = seeded
    app = create_app(engine=engine, client_factory=lambda site: wiki)
    with TestClient(app) as c:
        yield c


def test_enqueue_does_not_fetch_and_drain_does(http, engine):
    enqueued = http.post(
        "/fetch/",
        json={"title": _INDEX, "label": LABEL},
    )
    assert enqueued.status_code == 202
    assert enqueued.json()["request"]["status"] == FetchStatus.pending.value
    assert http.get("/fetch/queue").json()["pending"] == 1

    with Session(engine) as session:
        assert session.exec(select(Page)).all() == []

    report = drain(http)
    assert report["handled"] == 1
    assert report["complete"] is True
    assert report["remaining"] == 0

    assert http.get("/fetch/queue").json()["pending"] == 0
    with Session(engine) as session:
        assert len(session.exec(select(Page)).all()) == 1


def test_drain_endpoint_passes_its_bounds_through(http):
    http.post("/fetch/", json={"title": _INDEX, "label": LABEL})
    http.post(
        "/fetch/",
        json={"title": "Page:Queue.djvu/1", "label": LABEL},
    )

    report = drain(http, batch=1, max_passes=1)
    assert report["handled"] == 1
    assert report["stop_reason"] == DrainStop.max_passes.value
    assert report["complete"] is False
    assert report["remaining"] == 1


def test_queue_endpoint_does_not_drain(http, engine):
    http.post("/fetch/", json={"title": _INDEX, "label": LABEL})

    assert http.get("/fetch/queue").json()["pending"] == 1
    assert http.get("/fetch/queue").json()["pending"] == 1  # still queued

    with Session(engine) as session:
        assert session.exec(select(Page)).all() == []
