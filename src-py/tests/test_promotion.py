from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.main import create_app
from wtbot.model import (
    FileBlob,
    NsRole,
    Page,
    PageMeta,
    Promotion,
    Site,
    SiteCredential,
)
from wtbot.revision_store import record_head_revision
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemotePage

"""The push queue: staging what a sync report says is writable, then writing it
one page at a time.

The three things this pins are the three that make a push safe to press:

- **only writable rows are staged.** An unlinked page a comparison likes is
  refused, not silently promoted -- staging is the last point at which "we are
  not sure these correspond" is cheap to say.
- **nothing runs unapproved.** "Did a person agree to this" is stored, not
  assumed from the fact that a request arrived.
- **the frozen body is re-checked.** A source that moved between review and
  execution is a conflict, because the body under review is no longer the body
  that would be written.

One page per call throughout: a rate-limited wiki gets one request, a reviewer
can stop between pages, and a batch that half-succeeds carries its outcome per
row rather than as a single verdict over three hundred.
"""

INDEX = "Index:Varieties.djvu"
WHEN = datetime(2026, 1, 1, tzinfo=timezone.utc)
SHA1 = "a" * 40


def body(level: int, user: str, words: str) -> str:
    return (
        f'<noinclude><pagequality level="{level}" user="{user}" /></noinclude>'
        f"{words}<noinclude></noinclude>"
    )


def seed(engine, *, target_page: bool = True, linked: bool = True) -> None:
    """A one-page work. `target_page` off makes it a create; `linked` off
    leaves the pair matching but unasserted."""
    with Session(engine) as session:
        sites = {}
        for label in ("upstream", "local"):
            site = Site(family=label, code="en", label=label)
            session.add(site)
            session.commit()
            session.refresh(site)
            session.add(
                SiteCredential(site_pk=site.pk, username=f"{label}-bot", password="x")
            )
            session.commit()
            sites[label] = site
            index = Page(
                site_pk=site.pk,
                title=INDEX,
                namespace_role=NsRole.index,
                content_model="proofread-index",
                revid=1,
            )
            session.add(index)
            session.commit()
            file_page = Page(
                site_pk=site.pk, title="File:Varieties.djvu", namespace_role=NsRole.file
            )
            session.add(file_page)
            session.commit()
            session.refresh(file_page)
            session.add(FileBlob(page_pk=file_page.pk, file_sha1=SHA1, page_count=1))
            session.commit()

        def page(label: str, text: str, revid: int, parentid: int | None = None):
            title = "Page:Varieties.djvu/1"
            row = Page(
                site_pk=sites[label].pk,
                title=title,
                namespace_role=NsRole.page,
                content_model="proofread-page",
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            session.add(PageMeta(page_pk=row.pk, index_title=INDEX, page_number=1))
            session.commit()
            record_head_revision(
                session,
                row,
                RemotePage(
                    title=title,
                    namespace_key=250,
                    namespace_canonical="Page",
                    content_model="proofread-page",
                    text=text,
                    revid=revid,
                    parentid=parentid,
                    timestamp=WHEN,
                ),
            )
            session.commit()
            return row

        page("upstream", body(3, "Them", "Words."), 900)
        if target_page:
            page("local", body(3, "Us", "Words."), 254)

    if target_page and linked:
        _link(engine)


def _link(engine) -> None:
    from wtbot.matching import confirm_proposals, propose_index_links

    with Session(engine) as session:
        upstream = session.exec(select(Site).where(Site.label == "upstream")).one()
        local = session.exec(select(Site).where(Site.label == "local")).one()
        proposals = propose_index_links(
            session,
            local_site=upstream,
            remote_site=local,
            local_index_title=INDEX,
        )
        confirm_proposals(session, [p for p in proposals if p.proposable])
        session.commit()


def move_source(engine) -> None:
    """An edit upstream after the batch was staged."""
    with Session(engine) as session:
        upstream = session.exec(select(Site).where(Site.label == "upstream")).one()
        page = session.exec(
            select(Page).where(
                Page.site_pk == upstream.pk, Page.title == "Page:Varieties.djvu/1"
            )
        ).one()
        record_head_revision(
            session,
            page,
            RemotePage(
                title=page.title,
                namespace_key=250,
                namespace_canonical="Page",
                content_model="proofread-page",
                text=body(3, "Them", "Words, changed again."),
                revid=999,
                parentid=901,
                timestamp=WHEN,
            ),
        )
        session.commit()


class RecordingWiki(FakeWikiClient):
    """A wiki that records what it was asked to save."""

    saved: list[tuple] = []

    def save_page(self, title, text, base_revid, comment, *, force=False):
        RecordingWiki.saved.append((title, text, base_revid, force))
        from wtbot.wiki.wiki_types import SaveResult

        return SaveResult(revid=4242)


class RefusingWiki(FakeWikiClient):
    def save_page(self, title, text, base_revid, comment, *, force=False):
        from wtbot.wiki.wiki_types import EditConflict

        raise EditConflict(title, base_revid or 0, 777)


@pytest.fixture
def pushing_client(engine):
    RecordingWiki.saved = []
    wiki = RecordingWiki(pages={})
    return TestClient(create_app(engine=engine, client_factory=lambda site: wiki))


def stage(client, **overrides) -> dict:
    payload = {
        "source_label": "upstream",
        "target_label": "local",
        "index_title": INDEX,
        **overrides,
    }
    return client.post("/sync/batches", json=payload)


# -- staging ------------------------------------------------------------------


def test_a_batch_stages_only_what_the_report_would_write(pushing_client, engine):
    seed(engine)
    # Move upstream so the linked pair reports `push` rather than in_sync.
    move_source(engine)

    created = stage(pushing_client)
    assert created.status_code == 201, created.text
    batch = created.json()

    assert batch["status"] == "draft"
    (promotion,) = batch["promotions"]
    assert promotion["intent"] == "update"
    assert promotion["status"] == "staged"
    assert promotion["base_revid"] == 254  # the target head it claims to follow


def test_an_unlinked_page_cannot_be_staged(pushing_client, engine):
    """The rule staging exists to enforce. The two pages match and a comparison
    would happily link them -- but nobody has, so there is no base to replay
    onto and no row to queue."""
    seed(engine, linked=False)
    move_source(engine)

    refused = stage(pushing_client)
    assert refused.status_code == 409
    assert "needs linking first" in refused.json()["detail"]


def test_a_missing_target_page_stages_as_a_create(pushing_client, engine):
    seed(engine, target_page=False)

    batch = stage(pushing_client).json()
    (promotion,) = batch["promotions"]
    assert promotion["intent"] == "create"
    assert promotion["base_revid"] is None


def test_staging_rewrites_the_pagequality_user_to_the_pushing_account(
    pushing_client, engine
):
    """`user=` names an account on the *source* wiki. Writing it to the target
    attributes somebody's proofreading assessment to a username that may not
    exist there (discussion section 7)."""
    seed(engine, target_page=False)
    stage(pushing_client)

    with Session(engine) as session:
        (promotion,) = session.exec(select(Promotion)).all()
    assert 'user="local-bot"' in promotion.body
    assert "Them" not in promotion.body
    assert 'level="3"' in promotion.body  # the level is not touched


def test_staging_can_be_narrowed_to_chosen_pages(pushing_client, engine):
    seed(engine, target_page=False)

    empty = stage(pushing_client, page_numbers=[99])
    assert empty.status_code == 409
    assert stage(pushing_client, page_numbers=[1]).status_code == 201


# -- approval ------------------------------------------------------------------


def test_nothing_pushes_without_an_approval(pushing_client, engine):
    seed(engine, target_page=False)
    batch_pk = stage(pushing_client).json()["pk"]

    refused = pushing_client.post(f"/sync/batches/{batch_pk}/push", json={})
    assert refused.status_code == 409
    assert "approve it" in refused.json()["detail"]
    assert RecordingWiki.saved == []


def test_an_approval_records_who_gave_it(pushing_client, engine):
    seed(engine, target_page=False)
    batch_pk = stage(pushing_client).json()["pk"]

    approved = pushing_client.post(
        f"/sync/batches/{batch_pk}/approve", json={"approved_by": "tolland"}
    ).json()
    assert approved["status"] == "approved"
    assert approved["approved_by"] == "tolland"


def test_an_empty_approval_is_refused(pushing_client, engine):
    seed(engine, target_page=False)
    batch_pk = stage(pushing_client).json()["pk"]
    refused = pushing_client.post(
        f"/sync/batches/{batch_pk}/approve", json={"approved_by": "  "}
    )
    assert refused.status_code == 409


# -- pushing -------------------------------------------------------------------


def test_pushing_writes_one_page_and_records_the_result(pushing_client, engine):
    seed(engine, target_page=False)
    batch_pk = stage(pushing_client).json()["pk"]
    pushing_client.post(
        f"/sync/batches/{batch_pk}/approve", json={"approved_by": "tolland"}
    )

    after = pushing_client.post(f"/sync/batches/{batch_pk}/push", json={}).json()

    title, text, base_revid, _ = RecordingWiki.saved[0]
    assert title == "Page:Varieties.djvu/1"
    assert 'user="local-bot"' in text
    assert base_revid is None  # a create claims no base

    (promotion,) = after["promotions"]
    assert promotion["status"] == "pushed"
    assert promotion["result_revid"] == 4242
    assert after["status"] == "complete"
    assert after["remaining"] == 0


def test_an_update_sends_the_target_head_as_its_base(pushing_client, engine):
    """discussion section 8: baserevid, so the wiki refuses the write if the
    page moved. Two edits in the same second are indistinguishable by
    timestamp, and that is exactly a bot's workload."""
    seed(engine)
    move_source(engine)
    batch_pk = stage(pushing_client).json()["pk"]
    pushing_client.post(
        f"/sync/batches/{batch_pk}/approve", json={"approved_by": "tolland"}
    )
    pushing_client.post(f"/sync/batches/{batch_pk}/push", json={})

    _, _, base_revid, _ = RecordingWiki.saved[0]
    assert base_revid == 254


def test_a_source_that_moved_after_staging_is_a_conflict(pushing_client, engine):
    """The frozen body is no longer what it claims to be, so the write is
    refused before it reaches the wiki."""
    seed(engine, target_page=False)
    batch_pk = stage(pushing_client).json()["pk"]
    pushing_client.post(
        f"/sync/batches/{batch_pk}/approve", json={"approved_by": "tolland"}
    )
    move_source(engine)

    after = pushing_client.post(f"/sync/batches/{batch_pk}/push", json={}).json()

    (promotion,) = after["promotions"]
    assert promotion["status"] == "conflict"
    assert "moved since this was staged" in promotion["error_message"]
    assert RecordingWiki.saved == []
    assert after["status"] == "partial"


def test_a_wiki_refusing_the_edit_is_a_status_not_a_crash(engine):
    """A batch pushed page by page must be able to continue after one refusal."""
    seed(engine, target_page=False)
    wiki = RefusingWiki(pages={})
    client = TestClient(create_app(engine=engine, client_factory=lambda site: wiki))

    batch_pk = stage(client).json()["pk"]
    client.post(f"/sync/batches/{batch_pk}/approve", json={"approved_by": "t"})
    after = client.post(f"/sync/batches/{batch_pk}/push", json={}).json()

    (promotion,) = after["promotions"]
    assert promotion["status"] == "conflict"
    assert after["status"] == "partial"


def test_a_target_that_already_holds_the_body_is_skipped(pushing_client, engine):
    """Writing it would append a revision that changes nothing, on somebody's
    watchlist."""
    seed(engine)
    move_source(engine)
    batch_pk = stage(pushing_client).json()["pk"]
    pushing_client.post(
        f"/sync/batches/{batch_pk}/approve", json={"approved_by": "tolland"}
    )
    # Make the target hold exactly the staged body.
    with Session(engine) as session:
        (promotion,) = session.exec(select(Promotion)).all()
        target = session.get(Page, promotion.target_page_pk)
        record_head_revision(
            session,
            target,
            RemotePage(
                title=target.title,
                namespace_key=250,
                namespace_canonical="Page",
                content_model="proofread-page",
                text=promotion.body,
                revid=255,
                parentid=254,
                timestamp=WHEN,
            ),
        )
        session.commit()

    after = pushing_client.post(f"/sync/batches/{batch_pk}/push", json={}).json()
    (row,) = after["promotions"]
    assert row["status"] == "skipped"
    assert RecordingWiki.saved == []


def test_pushing_an_empty_batch_says_so(pushing_client, engine):
    seed(engine, target_page=False)
    batch_pk = stage(pushing_client).json()["pk"]
    pushing_client.post(f"/sync/batches/{batch_pk}/approve", json={"approved_by": "t"})
    pushing_client.post(f"/sync/batches/{batch_pk}/push", json={})

    exhausted = pushing_client.post(f"/sync/batches/{batch_pk}/push", json={})
    assert exhausted.status_code == 409
    assert "no staged rows left" in exhausted.json()["detail"]


# -- stopping ------------------------------------------------------------------


def test_a_page_can_be_skipped_without_abandoning_the_run(pushing_client, engine):
    seed(engine, target_page=False)
    batch = stage(pushing_client).json()
    promotion_pk = batch["promotions"][0]["pk"]

    after = pushing_client.post(
        f"/sync/batches/{batch['pk']}/promotions/{promotion_pk}/skip"
    ).json()
    assert after["promotions"][0]["status"] == "skipped"
    assert after["remaining"] == 0


def test_aborting_skips_what_is_left_and_keeps_what_went(pushing_client, engine):
    """No undo, and not pretending otherwise: reversing a push means appending
    another revision, which is its own piece of work."""
    seed(engine, target_page=False)
    batch_pk = stage(pushing_client).json()["pk"]
    pushing_client.post(f"/sync/batches/{batch_pk}/approve", json={"approved_by": "t"})

    after = pushing_client.post(f"/sync/batches/{batch_pk}/abort").json()
    assert after["status"] == "aborted"
    assert after["promotions"][0]["status"] == "skipped"
    assert RecordingWiki.saved == []


def test_a_pushed_batch_is_listed(pushing_client, engine):
    seed(engine, target_page=False)
    stage(pushing_client)
    listed = pushing_client.get("/sync/batches").json()
    assert len(listed) == 1
    assert listed[0]["source_site"] == "upstream"
    assert listed[0]["target_site"] == "local"


def test_an_unknown_batch_is_a_404(pushing_client):
    assert pushing_client.get("/sync/batches/999").status_code == 404


# -- single-page promotion: /sync/page-report and /sync/page-batches --------
#
# The embarrassment-risk workflow: one page, reviewed and pushed on its own,
# no fan-out to a whole work. Same rules as the batch path -- only what a push
# would actually write can be staged -- reusing the same Promotion/Batch rows
# so the review/approve/push screens need nothing page-specific.

PAGE_TITLE = "Page:Varieties.djvu/1"


def page_report(client, **overrides) -> dict:
    payload = {
        "source_label": "upstream",
        "target_label": "local",
        "source_title": PAGE_TITLE,
        **overrides,
    }
    return client.post("/sync/page-report", json=payload)


def stage_page_request(client, **overrides) -> dict:
    payload = {
        "source_label": "upstream",
        "target_label": "local",
        "source_title": PAGE_TITLE,
        **overrides,
    }
    return client.post("/sync/page-batches", json=payload)


def test_page_report_compares_exactly_the_named_page(pushing_client, engine):
    seed(engine)
    move_source(engine)

    report = page_report(pushing_client)
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["source_site"] == "upstream"
    assert body["target_site"] == "local"
    assert body["page"]["verdict"] == "push"
    assert body["page"]["actionable"] is True


def test_page_report_on_an_uncached_page_is_a_404(pushing_client, engine):
    seed(engine)
    missing = page_report(pushing_client, source_title="Page:Nope.djvu/1")
    assert missing.status_code == 404


def test_a_page_batch_stages_exactly_one_promotion(pushing_client, engine):
    seed(engine)
    move_source(engine)

    created = stage_page_request(pushing_client)
    assert created.status_code == 201, created.text
    batch = created.json()
    assert batch["status"] == "draft"
    (promotion,) = batch["promotions"]
    assert promotion["intent"] == "update"
    assert promotion["status"] == "staged"
    assert promotion["base_revid"] == 254


def test_an_unlinked_page_cannot_be_staged_as_a_page_batch(pushing_client, engine):
    seed(engine, linked=False)
    move_source(engine)

    refused = stage_page_request(pushing_client)
    assert refused.status_code == 409


def test_a_staged_page_batch_pushes_through_the_ordinary_batch_endpoints(
    pushing_client, engine
):
    """No page-specific push path -- a batch of one is still a batch."""
    seed(engine, target_page=False)
    batch = stage_page_request(pushing_client).json()
    pushing_client.post(
        f"/sync/batches/{batch['pk']}/approve", json={"approved_by": "t"}
    )

    pushed = pushing_client.post(f"/sync/batches/{batch['pk']}/push").json()
    assert pushed["status"] == "complete"
    assert pushed["promotions"][0]["status"] == "pushed"
    assert pushed["promotions"][0]["result_revid"] == 4242
