"""Commit worker: drains uncommitted EditJournal rows, pushes each page's
latest local save to the wiki via pywikibot, and records the outcome.

Mirrors worker.py's shape (plain functions over a Session + ClientFactory) so
it's testable with FakeWikiClient the same way the fetch worker is.

Push granularity is per-page, not per-journal-row: only the most recent
uncommitted body for a page is ever pushed (intermediate IDE saves are local
history, not separate wiki edits). The worker snapshots the journal rows it is
about to push, releases the SQLite transaction while the wiki save happens, and
then marks only that snapshotted batch committed on success. New saves that
arrive during the remote call remain pending for a later run.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from sqlmodel import Session, select

from wtbot.model import Commit, CommitStatus, EditJournal, Page, Site
from wtbot.wiki.client import WikiClient
from wtbot.wiki.wiki_types import EditConflict

ClientFactory = Callable[[Site], WikiClient]

_worker_lock = Lock()


@dataclass(frozen=True)
class _PendingPageCommit:
    """DB snapshot for one remote save attempt.

    This object is intentionally made only from scalar/copied values so the DB
    transaction that loaded it can be closed before pywikibot does network I/O.
    """

    page_pk: int
    title: str
    site: Site
    journal_pks: tuple[int, ...]
    base_revid: int
    body: str
    comment: str | None


@dataclass(frozen=True)
class _OrphanedPendingPage:
    page_pk: int


@dataclass(frozen=True)
class _CommitOutcome:
    status: CommitStatus
    result_revid: int | None = None
    remote_timestamp: datetime | None = None
    error_message: str | None = None


def run_pending_commits(
    session: Session,
    client_factory: ClientFactory,
    *,
    limit: int = 100,
    exclude: set[int] | None = None,
) -> tuple[int, set[int]]:
    """Push up to `limit` pages' worth of pending local edits.

    Returns ``(handled, failed_page_pks)`` where *failed_page_pks* is the set
    of page primary keys whose push did not succeed (conflict or error) this
    run. The caller should pass this back as *exclude* on a subsequent call so
    failed pages are not retried in the same sweep.
    """
    # The previous long SQLite write transaction also serialized concurrent
    # commit runs. Preserve that behavior without holding the DB lock while the
    # wiki save is in flight.
    with _worker_lock:
        try:
            return _run_pending_commits_unlocked(
                session, client_factory, limit=limit, exclude=exclude
            )
        finally:
            # This worker deliberately opens and closes several short
            # transactions. The caller's Session is shared with FastAPI
            # dependency cleanup, so leave it visibly idle even if a future
            # branch returns early or raises after an implicit SELECT.
            session.rollback()


def run_pending_commit_for_page(
    session: Session,
    page_pk: int,
    client_factory: ClientFactory,
) -> bool:
    """Push one page's pending local edits.

    Returns True on a successful remote save. Returns False when the page has a
    pending batch but the remote save records a conflict/error. Missing pending
    rows are treated as a no-op success by the lower-level worker.
    """
    with _worker_lock:
        try:
            return _push_page(session, page_pk, client_factory)
        finally:
            session.rollback()


def _run_pending_commits_unlocked(
    session: Session,
    client_factory: ClientFactory,
    *,
    limit: int,
    exclude: set[int] | None,
) -> tuple[int, set[int]]:
    attempted: set[int] = set(exclude or ())
    failed: set[int] = set()
    handled = 0
    while handled < limit:
        page_pk = _claim_next_page(session, exclude=attempted)
        if page_pk is None:
            break
        attempted.add(page_pk)
        ok = _push_page(session, page_pk, client_factory)
        if not ok:
            failed.add(page_pk)
        handled += 1
    return handled, failed


def _claim_next_page(session: Session, *, exclude: set[int]) -> int | None:
    """Return the oldest pending page not already attempted in this run."""
    try:
        rows = session.exec(
            select(EditJournal.page_pk)
            .where(EditJournal.committed == False)  # noqa: E712
            .order_by(EditJournal.saved_at)
        ).all()
        for page_pk in rows:
            if page_pk not in exclude:
                return page_pk
        return None
    finally:
        # Even this read starts BEGIN IMMEDIATE in this application. End it
        # before any later wiki/client work can happen.
        session.rollback()


def _push_page(session: Session, page_pk: int, client_factory: ClientFactory) -> bool:
    """Return True if the page was successfully pushed, False on conflict/error."""
    pending = _load_pending_page_commit(session, page_pk)
    if isinstance(pending, _OrphanedPendingPage):
        # Orphaned journal rows (page deleted locally) -- drop them rather
        # than spin forever on a page that no longer exists.
        logging.debug("Orphaned journal row for page %s", page_pk)
        _drop_orphaned_journal(session, page_pk)
        return True  # removed from queue; not a retriable failure
    if pending is None:
        return True

    outcome = _save_pending_page(pending, client_factory)
    _record_commit_outcome(session, pending, outcome)
    return outcome.status == CommitStatus.success


def _load_pending_page_commit(
    session: Session, page_pk: int
) -> _PendingPageCommit | _OrphanedPendingPage | None:
    """Load and detach the exact local journal batch that will be pushed.

    The session is always rolled back before returning. In this codebase a
    SELECT opens ``BEGIN IMMEDIATE``, so keeping ORM objects attached while
    calling the wiki would keep SQLite's write lock for the whole network call.
    """
    try:
        page = session.get(Page, page_pk)
        if page is None:
            return _OrphanedPendingPage(page_pk)

        pending = session.exec(
            select(EditJournal)
            .where(
                EditJournal.page_pk == page_pk,
                EditJournal.committed == False,  # noqa: E712
            )
            .order_by(EditJournal.saved_at)
        ).all()
        if not pending:
            return None

        site = session.get(Site, page.site_pk)
        if site is None:
            raise RuntimeError(f"page {page_pk} references missing site {page.site_pk}")

        journal_pks = tuple(row.pk for row in pending if row.pk is not None)
        if len(journal_pks) != len(pending):
            raise RuntimeError(f"page {page_pk} has unpersisted journal rows")

        latest = pending[-1]
        base_revid = (
            latest.base_revid if latest.base_revid is not None else (page.revid or 0)
        )
        return _PendingPageCommit(
            page_pk=page_pk,
            title=page.title,
            site=_copy_site(site),
            journal_pks=journal_pks,
            base_revid=base_revid,
            body=latest.body,
            comment=latest.comment,
        )
    finally:
        session.rollback()


def _copy_site(site: Site) -> Site:
    return Site(
        pk=site.pk,
        family=site.family,
        code=site.code,
        articlepath=site.articlepath,
        host=site.host,
        api_url=site.api_url,
        label=site.label,
        created_at=site.created_at,
    )


def _save_pending_page(
    pending: _PendingPageCommit, client_factory: ClientFactory
) -> _CommitOutcome:
    """Perform the remote save without any DB transaction held."""
    try:
        client = client_factory(pending.site)
        result = client.save_page(
            pending.title, pending.body, pending.base_revid, pending.comment
        )
        return _CommitOutcome(
            status=CommitStatus.success,
            result_revid=result.revid,
            remote_timestamp=result.timestamp,
        )
    except EditConflict as exc:
        return _CommitOutcome(status=CommitStatus.conflict, error_message=str(exc))
    except Exception as exc:  # noqa: BLE001 - record any failure on the row
        return _CommitOutcome(
            status=CommitStatus.error,
            error_message=f"{type(exc).__name__}: {exc}",
        )


def _record_commit_outcome(
    session: Session, pending: _PendingPageCommit, outcome: _CommitOutcome
) -> None:
    commit = Commit(
        page_pk=pending.page_pk,
        base_revid=pending.base_revid,
        submitted_body=pending.body,
        comment=pending.comment,
        status=outcome.status,
        result_revid=outcome.result_revid,
        error_message=outcome.error_message,
    )
    try:
        if outcome.status == CommitStatus.success:
            page = session.get(Page, pending.page_pk)
            if page is not None:
                page.revid = outcome.result_revid
                page.remote_timestamp = outcome.remote_timestamp
                page.dirty = _has_uncaptured_pending_edits(session, pending)
                session.add(page)

            rows = session.exec(
                select(EditJournal).where(EditJournal.pk.in_(pending.journal_pks))
            ).all()
            for row in rows:
                row.committed = True
                session.add(row)

        session.add(commit)
        session.commit()
    except Exception:
        session.rollback()
        raise


def _has_uncaptured_pending_edits(
    session: Session, pending: _PendingPageCommit
) -> bool:
    row = session.exec(
        select(EditJournal.pk)
        .where(
            EditJournal.page_pk == pending.page_pk,
            EditJournal.committed == False,  # noqa: E712
            ~EditJournal.pk.in_(pending.journal_pks),
        )
        .limit(1)
    ).first()
    return row is not None


def _drop_orphaned_journal(session: Session, page_pk: int) -> None:
    try:
        rows = session.exec(
            select(EditJournal).where(
                EditJournal.page_pk == page_pk,
                EditJournal.committed == False,  # noqa: E712
            )
        ).all()
        for row in rows:
            row.committed = True
            session.add(row)
        session.commit()
    except Exception:
        session.rollback()
        raise
