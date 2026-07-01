"""Tests for the commit worker -- pushing local EditJournal rows to the wiki."""

from __future__ import annotations

from types import SimpleNamespace

from sqlmodel import Session, select

from wtbot.api.commit import list_pending_commits, run_commit_for_page
from wtbot.commit_worker import run_pending_commits
from wtbot.sqlmodel import Commit, CommitStatus, EditJournal, Page, Site
from wtbot.sqlmodel.namespace import NsRole
from wtbot.wiki.client import FakeWikiClient
from wtbot.wiki.wiki_types import RemotePage, SaveResult

TITLE = "Page:Foo.djvu/1"


def _setup(engine, *, remote_text="original", remote_revid=100):
    with Session(engine) as s:
        site = Site(family="wikisource", code="en")
        s.add(site)
        s.commit()
        s.refresh(site)

        page = Page(
            site_pk=site.pk,
            title=TITLE,
            namespace_role=NsRole.page,
            content_model="proofread-page",
            text=remote_text,
            revid=remote_revid,
        )
        s.add(page)
        s.commit()
        s.refresh(page)
        return site, page


def _client_factory(fake: FakeWikiClient):
    return lambda site: fake


class SaveHookClient(FakeWikiClient):
    def __init__(self, *args, on_save, **kwargs):
        super().__init__(*args, **kwargs)
        self._on_save = on_save

    def save_page(
        self, title: str, text: str, base_revid: int | None, comment: str | None
    ) -> SaveResult:
        self._on_save()
        return super().save_page(title, text, base_revid, comment)


def test_push_single_save_succeeds(engine):
    site, page = _setup(engine)
    fake = FakeWikiClient(
        pages={
            TITLE: RemotePage(
                title=TITLE,
                namespace_key=0,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="original",
                revid=100,
            )
        }
    )

    with Session(engine) as s:
        s.add(
            EditJournal(page_pk=page.pk, base_revid=100, body="edited", comment="fix")
        )
        s.commit()

    with Session(engine) as s:
        handled, _failed = run_pending_commits(s, _client_factory(fake))
        assert handled == 1

        updated = s.get(Page, page.pk)
        assert (
            updated.text == "original"
        )  # cache text untouched by push (read_content already had it)
        assert updated.revid == 101
        assert updated.dirty is False

        journal = s.exec(
            select(EditJournal)
            .where(EditJournal.page_pk == page.pk)
            .order_by(EditJournal.pk)
        ).all()
        assert all(j.committed for j in journal)

        commit = s.exec(select(Commit).where(Commit.page_pk == page.pk)).first()
        assert commit.status == CommitStatus.success
        assert commit.result_revid == 101

    assert fake._pages[TITLE].text == "edited"


def test_multiple_saves_collapse_into_one_push(engine):
    site, page = _setup(engine)
    fake = FakeWikiClient(
        pages={
            TITLE: RemotePage(
                title=TITLE,
                namespace_key=0,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="original",
                revid=100,
            )
        }
    )

    with Session(engine) as s:
        s.add(EditJournal(page_pk=page.pk, base_revid=100, body="draft 1"))
        s.add(EditJournal(page_pk=page.pk, base_revid=100, body="draft 2 final"))
        s.commit()

    with Session(engine) as s:
        handled, _failed = run_pending_commits(s, _client_factory(fake))
        assert handled == 1
        commits = s.exec(select(Commit).where(Commit.page_pk == page.pk)).all()
        assert len(commits) == 1
        assert commits[0].submitted_body == "draft 2 final"

    assert fake._pages[TITLE].text == "draft 2 final"


def test_local_save_during_remote_push_remains_pending(engine):
    site, page = _setup(engine)

    with Session(engine) as s:
        s.add(EditJournal(page_pk=page.pk, base_revid=100, body="first edit"))
        db_page = s.get(Page, page.pk)
        db_page.dirty = True
        s.add(db_page)
        s.commit()

    def save_new_local_edit():
        with Session(engine) as s:
            db_page = s.get(Page, page.pk)
            db_page.text = "second edit"
            db_page.dirty = True
            s.add(db_page)
            s.add(EditJournal(page_pk=page.pk, base_revid=100, body="second edit"))
            s.commit()

    fake = SaveHookClient(
        pages={
            TITLE: RemotePage(
                title=TITLE,
                namespace_key=0,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="original",
                revid=100,
            )
        },
        on_save=save_new_local_edit,
    )

    with Session(engine) as s:
        handled, failed = run_pending_commits(s, _client_factory(fake))
        assert handled == 1
        assert failed == set()

    assert fake._pages[TITLE].text == "first edit"

    with Session(engine) as s:
        updated = s.get(Page, page.pk)
        assert updated.text == "second edit"
        assert updated.revid == 101
        assert updated.dirty is True

        journal = s.exec(
            select(EditJournal)
            .where(EditJournal.page_pk == page.pk)
            .order_by(EditJournal.pk)
        ).all()
        assert [row.body for row in journal] == ["first edit", "second edit"]
        assert [row.committed for row in journal] == [True, False]

        commits = s.exec(select(Commit).where(Commit.page_pk == page.pk)).all()
        assert len(commits) == 1
        assert commits[0].status == CommitStatus.success
        assert commits[0].submitted_body == "first edit"


def test_remote_conflict_recorded_not_raised(engine):
    site, page = _setup(engine)
    # Remote has moved on to revid 200 since the local edit was based on 100.
    fake = FakeWikiClient(
        pages={
            TITLE: RemotePage(
                title=TITLE,
                namespace_key=0,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="someone else's edit",
                revid=200,
            )
        }
    )

    with Session(engine) as s:
        s.add(EditJournal(page_pk=page.pk, base_revid=100, body="my edit"))
        s.commit()

    with Session(engine) as s:
        handled, failed = run_pending_commits(s, _client_factory(fake))
        assert handled == 1
        assert page.pk in failed  # caller must exclude from subsequent sweeps

        commit = s.exec(select(Commit).where(Commit.page_pk == page.pk)).first()
        assert commit.status == CommitStatus.conflict

        # Not committed -- stays in the queue for the user to resolve/retry.
        journal = s.exec(
            select(EditJournal).where(EditJournal.page_pk == page.pk)
        ).first()
        assert journal.committed is False

        updated = s.get(Page, page.pk)
        assert updated.revid == 100  # unchanged


def test_remote_conflict_releases_db_lock(engine):
    site, page = _setup(engine)
    fake = FakeWikiClient(
        pages={
            TITLE: RemotePage(
                title=TITLE,
                namespace_key=0,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="someone else's edit",
                revid=200,
            )
        }
    )

    with Session(engine) as s:
        s.add(EditJournal(page_pk=page.pk, base_revid=100, body="my edit"))
        s.commit()

    with Session(engine) as worker_session:
        handled, failed = run_pending_commits(worker_session, _client_factory(fake))
        assert handled == 1
        assert failed == {page.pk}
        assert worker_session.in_transaction() is False

        with Session(engine) as other_session:
            other_session.add(Site(family="wikisource", code="fr"))
            other_session.commit()


def test_pending_commit_api_lists_and_pushes_one_page(engine):
    site, page = _setup(engine)
    fake = FakeWikiClient(
        pages={
            TITLE: RemotePage(
                title=TITLE,
                namespace_key=0,
                namespace_canonical="Page",
                content_model="proofread-page",
                text="original",
                revid=100,
            )
        }
    )

    with Session(engine) as s:
        s.add(EditJournal(page_pk=page.pk, base_revid=100, body="draft 1"))
        s.add(EditJournal(page_pk=page.pk, base_revid=100, body="draft 2 final"))
        s.commit()

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(client_factory=_client_factory(fake)))
    )
    with Session(engine) as s:
        pending = list_pending_commits(session=s)
        assert len(pending) == 1
        assert pending[0].page_pk == page.pk
        assert pending[0].pending_count == 2
        assert pending[0].submitted_body == "draft 2 final"

        commit = run_commit_for_page(page.pk, request, session=s)
        assert commit.status == CommitStatus.success
        assert commit.submitted_body == "draft 2 final"

        assert list_pending_commits(session=s) == []


def test_no_pending_edits_is_a_noop(engine):
    _setup(engine)
    fake = FakeWikiClient()
    with Session(engine) as s:
        handled, _failed = run_pending_commits(s, _client_factory(fake))
    assert handled == 0
