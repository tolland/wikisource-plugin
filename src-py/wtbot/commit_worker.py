"""Commit worker: drains uncommitted EditJournal rows, pushes each page's
latest local save to the wiki via pywikibot, and records the outcome.

Mirrors worker.py's shape (plain functions over a Session + ClientFactory) so
it's testable with FakeWikiClient the same way the fetch worker is.

Push granularity is per-page, not per-journal-row: only the most recent
uncommitted body for a page is ever pushed (intermediate IDE saves are local
history, not separate wiki edits). All uncommitted rows for that page are
marked committed together once the push succeeds, so a rapid sequence of
saves between commit-worker runs results in one wiki edit, not several.
"""

from collections.abc import Callable

from sqlmodel import Session, select

from wtbot.settings import WikiSettings
from wtbot.sqlmodel import Commit, CommitStatus, EditJournal, Page, Site
from wtbot.wiki.client import WikiClient, get_wiki_client
from wtbot.wiki.types import EditConflict

ClientFactory = Callable[[Site], WikiClient]


def make_client_for_site(site: Site) -> WikiClient:
    return get_wiki_client(WikiSettings.from_site(site))


def run_pending_commits(
    session: Session,
    client_factory: ClientFactory,
    *,
    limit: int = 100,
) -> int:
    """Push up to `limit` pages' worth of pending local edits. Returns how
    many pages were handled."""
    handled = 0
    attempted: set[int] = set()
    while handled < limit:
        page_pk = _claim_next_page(session, exclude=attempted)
        if page_pk is None:
            break
        attempted.add(page_pk)
        _push_page(session, page_pk, client_factory)
        handled += 1
    return handled


def _claim_next_page(session: Session, *, exclude: set[int]) -> int | None:
    """Returns the page_pk of the oldest page with an uncommitted edit not
    already attempted this run, or None if the queue is empty. A page whose
    push failed (conflict/error) stays uncommitted but is skipped for the
    rest of this run rather than retried in a tight loop."""
    row = session.exec(
        select(EditJournal.page_pk)
        .where(EditJournal.committed == False)  # noqa: E712
        .order_by(EditJournal.saved_at)
    ).all()
    for page_pk in row:
        if page_pk not in exclude:
            return page_pk
    return None


def _push_page(session: Session, page_pk: int, client_factory: ClientFactory) -> None:
    page = session.get(Page, page_pk)
    if page is None:
        # Orphaned journal rows (page deleted locally) -- drop them rather
        # than spin forever on a page that no longer exists.
        _drop_orphaned_journal(session, page_pk)
        return

    pending = session.exec(
        select(EditJournal)
        .where(
            EditJournal.page_pk == page_pk, EditJournal.committed == False  # noqa: E712
        )  # noqa: E712
        .order_by(EditJournal.saved_at)
    ).all()
    if not pending:
        return

    latest = pending[-1]
    commit = Commit(
        page_pk=page_pk,
        base_revid=(
            latest.base_revid if latest.base_revid is not None else (page.revid or 0)
        ),
        submitted_body=latest.body,
        comment=latest.comment,
    )

    site = session.get(Site, page.site_pk)
    try:
        client = client_factory(site)
        result = client.save_page(
            page.title, latest.body, commit.base_revid, commit.comment
        )
        commit.status = CommitStatus.success
        commit.result_revid = result.revid

        page.revid = result.revid
        page.remote_timestamp = result.timestamp
        page.dirty = False
        session.add(page)

        for row in pending:
            row.committed = True
            session.add(row)
    except EditConflict as exc:
        commit.status = CommitStatus.conflict
        commit.error_message = str(exc)
    except Exception as exc:  # noqa: BLE001 - record any failure on the row
        commit.status = CommitStatus.error
        commit.error_message = f"{type(exc).__name__}: {exc}"

    session.add(commit)
    session.commit()


def _drop_orphaned_journal(session: Session, page_pk: int) -> None:
    rows = session.exec(
        select(EditJournal).where(
            EditJournal.page_pk == page_pk, EditJournal.committed == False  # noqa: E712
        )  # noqa: E712
    ).all()
    for row in rows:
        row.committed = True
        session.add(row)
    session.commit()
