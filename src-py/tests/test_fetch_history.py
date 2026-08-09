from datetime import datetime, timedelta, timezone

import pytest
from conftest import fetch_and_drain, register_site
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.main import create_app
from wtbot.model import FetchStatus, Page, Revision
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemotePage

"""Fetching with ``revisions > 1``: the history walk behind the head.

This path had no test, and shipped broken -- ``_record_history`` read
``page.revid`` off the ``CachedPage`` snapshot, which carries five fields and
not that one. Every deep fetch raised ``AttributeError`` *after* the head had
been written, so the page was cached correctly and the request was marked
``error`` anyway.

Two things are pinned here, because the bug needed both to be wrong to hurt:

- the walk works, and the revisions land where the anchor search reads them;
- when it does *not* work, the fetch still succeeds. History is an enrichment
  for cross-site matching; losing it downgrades a comparison to
  ``history_exhausted``, which is a state every caller already handles. An
  enrichment that can fail a fetch is not an enrichment.
"""

LABEL = "test"
TITLE = "Page:Hertz.pdf/8"
WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)


def revision(revid: int, parentid: int | None, text: str) -> RemotePage:
    return RemotePage(
        title=TITLE,
        namespace_key=250,
        namespace_canonical="Page",
        content_model="proofread-page",
        text=text,
        revid=revid,
        parentid=parentid,
        timestamp=WHEN + timedelta(days=revid),
    )


HISTORY = [
    revision(3, 2, "Third."),  # head, newest first as the API returns them
    revision(2, 1, "Second."),
    revision(1, None, "First."),
]


@pytest.fixture
def app_with_history(engine):
    wiki = FakeWikiClient(pages={TITLE: HISTORY[0]}, history={TITLE: HISTORY})
    app = create_app(engine=engine, client_factory=lambda site: wiki)
    client = TestClient(app)
    register_site(client, label=LABEL)
    return client


def test_a_deep_fetch_stores_the_revisions_behind_the_head(app_with_history, engine):
    result = fetch_and_drain(
        app_with_history, {"title": TITLE, "label": LABEL, "revisions": 5}
    )
    assert result["request"]["status"] == FetchStatus.done.value

    with Session(engine) as session:
        page = session.exec(select(Page).where(Page.title == TITLE)).one()
        revisions = session.exec(
            select(Revision).where(Revision.page_pk == page.pk).order_by(Revision.revid)
        ).all()

    assert [row.revid for row in revisions] == [1, 2, 3]
    # The head denormalisation is untouched by the walk: the processors and
    # every existing reader work from it, and a history walk must not change
    # what "current" means.
    assert page.revid == 3
    assert page.latest_revision_pk == next(r.pk for r in revisions if r.revid == 3)
    # And the run is contiguous back to the first revision, which is what lets
    # the anchor search say "diverged" rather than "we did not look far enough".
    assert page.history_complete_from_revid == 1


def test_a_shallow_fetch_walks_no_history(app_with_history, engine):
    """revisions=1 is the normal fetch: the head is all the VFS and the editor
    need, and the walk costs a request per page."""
    fetch_and_drain(app_with_history, {"title": TITLE, "label": LABEL})

    with Session(engine) as session:
        page = session.exec(select(Page).where(Page.title == TITLE)).one()
        revisions = session.exec(
            select(Revision).where(Revision.page_pk == page.pk)
        ).all()

    assert [row.revid for row in revisions] == [3]


def test_the_walk_is_bounded_by_the_requested_depth(app_with_history, engine):
    fetch_and_drain(app_with_history, {"title": TITLE, "label": LABEL, "revisions": 2})

    with Session(engine) as session:
        page = session.exec(select(Page).where(Page.title == TITLE)).one()
        revisions = session.exec(
            select(Revision).where(Revision.page_pk == page.pk).order_by(Revision.revid)
        ).all()

    assert [row.revid for row in revisions] == [2, 3]
    # The oldest held revision has a parent we do not hold, so the history is
    # known to be partial -- reported, not guessed at.
    assert page.history_complete_from_revid == 2


def test_a_deep_fetch_is_idempotent(app_with_history, engine):
    """Re-fetching a page whose history is already stored must not duplicate
    it: the queue is drained repeatedly, and a page is re-fetched by design."""
    for _ in range(2):
        fetch_and_drain(
            app_with_history, {"title": TITLE, "label": LABEL, "revisions": 5}
        )

    with Session(engine) as session:
        revisions = session.exec(select(Revision)).all()
    assert [row.revid for row in sorted(revisions, key=lambda r: r.revid)] == [1, 2, 3]


class BrokenHistoryClient(FakeWikiClient):
    """A wiki whose history call fails, standing in for every way it can."""

    def get_history(self, title: str, *, limit: int) -> list[RemotePage]:
        raise RuntimeError("upstream said no")


def test_a_failed_history_walk_does_not_fail_the_fetch(engine):
    """The contract the bug broke. The head fetched fine; the page is usable;
    only the cross-site comparison is poorer for it."""
    wiki = BrokenHistoryClient(pages={TITLE: HISTORY[0]})
    client = TestClient(create_app(engine=engine, client_factory=lambda site: wiki))
    register_site(client, label=LABEL)

    result = fetch_and_drain(client, {"title": TITLE, "label": LABEL, "revisions": 5})

    assert result["request"]["status"] == FetchStatus.done.value
    assert result["request"]["error_message"] is None
    assert result["page"]["revid"] == 3

    with Session(engine) as session:
        revisions = session.exec(select(Revision)).all()
    assert [row.revid for row in revisions] == [3]


class MalformedHistoryClient(FakeWikiClient):
    """History that cannot be recorded, rather than history that cannot be
    fetched -- the shape of the original bug, where the failure was in *our*
    code after the network call had already succeeded."""

    def get_history(self, title: str, *, limit: int) -> list[RemotePage]:
        return [HISTORY[0], "not a revision"]  # type: ignore[list-item]


def test_a_history_that_cannot_be_recorded_does_not_fail_the_fetch(engine):
    wiki = MalformedHistoryClient(pages={TITLE: HISTORY[0]})
    client = TestClient(create_app(engine=engine, client_factory=lambda site: wiki))
    register_site(client, label=LABEL)

    result = fetch_and_drain(client, {"title": TITLE, "label": LABEL, "revisions": 5})

    assert result["request"]["status"] == FetchStatus.done.value
    with Session(engine) as session:
        page = session.exec(select(Page).where(Page.title == TITLE)).one()
    assert page.revid == 3
    assert page.fetch_status == "done"
