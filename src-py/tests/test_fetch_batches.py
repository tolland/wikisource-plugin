"""Batch boundaries, site isolation, and individual queue outcomes."""

from sqlmodel import select

from wtbot.fetch.fetch_worker import run_pending
from wtbot.fetch.utils import _claim_batch
from wtbot.model import FetchRequest, FetchStatus, Page, Site
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemotePage, RemotePageImages


def remote(title, text="body", model="wikitext"):
    return RemotePage(
        title=title,
        namespace_key=0,
        namespace_canonical="",
        content_model=model,
        text=text,
    )


class BatchClient(FakeWikiClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.batches = []
        self.image_batches = []

    def get_pages(self, titles):
        self.batches.append(titles)
        return super().get_pages(titles)

    def get_page_images_bulk(self, titles):
        self.image_batches.append(titles)
        return super().get_page_images_bulk(titles)


def enqueue(session, site, titles, priority=0):
    session.add(site)
    session.commit()
    for title in titles:
        session.add(FetchRequest(site_pk=site.pk, title=title, priority=priority))
    session.commit()


def test_large_queue_batches_and_respects_worker_limit(session):
    titles = [f"Article {n}" for n in range(120)]
    client = BatchClient(pages={title: remote(title) for title in titles})
    enqueue(session, Site(family="a", code="en"), titles)
    assert run_pending(session, lambda _: client, limit=105) == 105
    assert [len(batch) for batch in client.batches] == [50, 50, 5]
    assert (
        sum(
            req.status == FetchStatus.pending
            for req in session.exec(select(FetchRequest))
        )
        == 15
    )
    assert run_pending(session, lambda _: client) == 15
    assert len(session.exec(select(Page)).all()) == 120


def test_same_titles_are_routed_to_their_own_site_and_image_cache(session):
    sites = [Site(family="a", code="en"), Site(family="b", code="en")]
    clients = {}
    title = "Page:Book.pdf/1"
    for site in sites:
        enqueue(session, site, [title])
        clients[site.pk] = BatchClient(
            pages={title: remote(title, site.family, "proofread-page")},
            page_images={
                title: RemotePageImages(thumbnail_url=f"https://{site.family}/scan")
            },
        )
    assert run_pending(session, lambda site: clients[site.pk], image_cache={}) == 2
    rows = session.exec(select(Page).where(Page.title == title)).all()
    assert {row.text for row in rows} == {"a", "b"}
    assert all(client.image_batches == [[title]] for client in clients.values())


def test_batch_claim_uses_highest_priority_site_and_ends_transaction(session):
    a, b = Site(family="a", code="en"), Site(family="b", code="en")
    enqueue(session, a, ["old"])
    enqueue(session, b, ["urgent", "urgent too"], priority=5)
    enqueue(session, a, ["other urgent"], priority=5)
    claimed = _claim_batch(session)
    assert [req.title for req in claimed] == ["urgent", "urgent too"]
    assert not session.in_transaction()
    assert [req.title for req in _claim_batch(session)] == ["other urgent"]
    assert [req.title for req in _claim_batch(session)] == ["old"]
    assert _claim_batch(session) == []


def test_missing_title_does_not_fail_siblings_or_duplicate_requests(session):
    client = BatchClient(pages={"exists": remote("exists")})
    enqueue(session, Site(family="a", code="en"), ["exists", "missing", "exists"])
    assert run_pending(session, lambda _: client) == 3
    assert [
        req.status
        for req in session.exec(select(FetchRequest).order_by(FetchRequest.pk))
    ] == [FetchStatus.done, FetchStatus.error, FetchStatus.done]
    assert len(session.exec(select(Page)).all()) == 1


def test_failed_bulk_request_is_not_retried_serially(session):
    class BrokenBatch(BatchClient):
        def get_pages(self, titles):
            self.batches.append(titles)
            raise RuntimeError("upstream unavailable")

        def get_page(self, title):
            raise AssertionError("must not retry individually")

    client = BrokenBatch()
    enqueue(session, Site(family="a", code="en"), ["one", "two"])
    assert run_pending(session, lambda _: client) == 2
    assert len(client.batches) == 1
    assert all(
        req.status == FetchStatus.error for req in session.exec(select(FetchRequest))
    )


def test_rate_limit_releases_unprocessed_claims_and_stops(session):
    from test_queue_runner import _TooManyRequests

    class LimitedBatch(BatchClient):
        def get_pages(self, titles):
            self.batches.append(titles)
            raise _TooManyRequests()

    client = LimitedBatch()
    enqueue(session, Site(family="a", code="en"), [f"Page {n}" for n in range(60)])
    failures = []
    assert run_pending(session, lambda _: client, on_failure=failures.append) == 1
    assert len(client.batches) == 1
    rows = session.exec(select(FetchRequest)).all()
    assert sum(row.status == FetchStatus.pending for row in rows) == 59
    assert sum(row.status == FetchStatus.in_progress for row in rows) == 0
    assert failures[0].retry_after == 45
