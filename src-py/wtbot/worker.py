import logging
from collections.abc import Callable
from pathlib import Path

from sqlmodel import Session, select

from wtbot.db_session import detached_site, read_snapshot, write_batch
from wtbot.failure_log import FailureContext, record_failure, site_label
from wtbot.model import (
    FetchRequest,
    FetchState,
    FetchStatus,
    Page,
    Site,
    role_for_canonical,
)
from wtbot.model.page_meta import PageMeta
from wtbot.page_processors import (
    CachedPage,
    ClaimedFetchRequest,
    PageProcessor,
    ProcessContext,
    processor_for,
)
from wtbot.promotion_store import materialize_promotion_links
from wtbot.revision_store import (
    RemoteIdentityError,
    head_revision,
    record_head_revision,
    record_history,
    validate_remote_identity,
)
from wtbot.timeutil import utcnow
from wtbot.wiki.client import WikiClient
from wtbot.wiki.failures import WikiFailure
from wtbot.wiki.namespaces import sync_namespaces
from wtbot.wiki.wiki_types import PageNotFound, RemotePage

"""Fetch worker: drains the FetchRequest queue, calls the wiki, writes results
back into the cache.

The worker owns the queue mechanics — claim, common Page upsert, progress
bookkeeping. Everything type-specific (blobs, index fan-out, scan-image
metadata) lives in ``wtbot.page_processors``, one class per page type.

Kept as plain functions over a Session + a client factory so it is fully
testable with FakeWikiClient and reusable from either the API, the drain
endpoint, or ``wtbot drain``.
"""

log = logging.getLogger(__name__)

ClientFactory = Callable[[Site], WikiClient]

#: Called with each classified failure as it is recorded. The failure is
#: already on the row; this exists so a caller draining a whole queue can react
#: to *why* a request failed -- notably to stop on a rate limit rather than
#: send the next two hundred requests at a wiki that just refused one.
FailureObserver = Callable[[WikiFailure], None]


def run_pending(
    session: Session,
    client_factory: ClientFactory,
    *,
    limit: int = 100,
    blob_root: Path | None = None,
    on_failure: FailureObserver | None = None,
    image_cache: dict | None = None,
) -> int:
    """Process up to ``limit`` pending requests. Returns how many were handled.

    ``image_cache`` is shared enrichment fetched in bulk (see
    ``page_processors``): an Index fan-out fills it for its children, and each
    child reads its own entry instead of asking the wiki again. Passing None
    disables the sharing -- every page then asks for itself, which is correct
    but costs a request each.
    """
    handled = 0
    while handled < limit:
        req = _claim_next(session)
        if req is None:
            break
        _process(
            session,
            req,
            client_factory,
            blob_root=blob_root,
            on_failure=on_failure,
            image_cache=image_cache,
        )
        handled += 1
    return handled


def _claim_next(session: Session) -> ClaimedFetchRequest | None:
    with read_snapshot(session):
        req = session.exec(
            select(FetchRequest)
            .where(FetchRequest.status == FetchStatus.pending)
            .order_by(FetchRequest.priority.desc(), FetchRequest.requested_at)
        ).first()
        if req is None:
            return None
        req.status = FetchStatus.in_progress
        req.updated_at = utcnow()
        session.add(req)
        claimed = _snapshot_request(req)
        session.commit()
        return claimed


def _snapshot_request(req: FetchRequest) -> ClaimedFetchRequest:
    if req.pk is None:
        raise RuntimeError("cannot process an unpersisted fetch request")
    return ClaimedFetchRequest(
        pk=req.pk,
        site_pk=req.site_pk,
        parent_pk=req.parent_pk,
        title=req.title,
        kind=req.kind,
        depth=req.depth,
        revisions=req.revisions,
    )


def _maybe_sync_namespaces(session: Session, site: Site, client: WikiClient) -> None:
    """Sync siteinfo namespaces on first use of a site (no-op on subsequent calls)."""
    from wtbot.model import Namespace

    with read_snapshot(session):
        already = session.exec(
            select(Namespace).where(Namespace.site_pk == site.pk)
        ).first()
    if already is not None:
        return
    ns_dict = client.get_namespaces()
    if ns_dict is None:
        return
    sync_namespaces(session, site, ns_dict)
    session.rollback()


def _process(
    session: Session,
    req: ClaimedFetchRequest,
    client_factory: ClientFactory,
    *,
    blob_root: Path | None = None,
    on_failure: FailureObserver | None = None,
    image_cache: dict | None = None,
) -> None:
    site = _load_site_snapshot(session, req.site_pk)
    status = FetchStatus.error
    progress_total = None
    progress_done = 0
    error_message = None
    try:
        client = client_factory(site)
        _maybe_sync_namespaces(session, site, client)
        remote = client.get_page(req.title)

        # Drive behaviour from what was actually fetched, not from req.kind.
        processor = processor_for(remote)
        page = _upsert_page(session, site, remote, processor)
        ctx = ProcessContext(
            session=session,
            site=site,
            client=client,
            request=req,
            blob_root=blob_root,
            image_cache=image_cache,
        )
        if req.revisions > 1:
            # After the head is recorded, never instead of it: the processor
            # and every existing reader work from the head denormalisation, and
            # a history walk must not change what "current" means.
            _record_history(session, client, page, req)

        _materialize_promotion_links(session, page)

        outcome = processor.postprocess(ctx, page, remote)
        status = outcome.status
        progress_total = outcome.progress_total
        progress_done = outcome.progress_done
    except PageNotFound:
        error_message = f"page not found: {req.title}"
    except Exception as exc:  # noqa: BLE001 - record any failure on the row
        # The row keeps a short summary; the traceback and the upstream HTTP
        # that preceded the failure go to the detail log (see failure_log).
        failure = record_failure(
            FailureContext(
                component="fetch",
                title=req.title,
                request_pk=req.pk,
                site_pk=req.site_pk,
                site_label=site_label(site),
                details={"kind": req.kind.value, "depth": str(req.depth)},
            ),
            exc,
        )
        error_message = failure.summary
        if on_failure is not None:
            on_failure(failure)

    _record_fetch_result(
        session,
        req,
        status=status,
        progress_total=progress_total,
        progress_done=progress_done,
        error_message=error_message,
    )


def _record_history(
    session: Session,
    client: WikiClient,
    page: CachedPage,
    req: ClaimedFetchRequest,
) -> None:
    """Fill in revisions behind the head, best effort.

    A failure here does not fail the fetch: the head is what the editor and the
    VFS need, and history is an enrichment for the anchor search. Losing it
    downgrades a match to `history_exhausted`, which is a state the caller
    already has to handle -- so *everything* here is guarded, not only the
    network call. An enrichment that can mark a successfully fetched page as
    errored is not best effort.

    The network call comes first and the database work second, in its own
    ``write_batch``: the session is idle when this is entered (``_upsert_page``
    committed), and rows flushed outside a batch would ride along on whatever
    the processor commits next.
    """
    try:
        history = client.get_history(req.title, limit=req.revisions)
    except Exception as exc:  # noqa: BLE001 - enrichment must not fail a fetch
        log.warning("history fetch failed for %s: %s", req.title, exc)
        return
    if not history:
        return

    try:
        with write_batch(session):
            # The ORM row, not the CachedPage snapshot the processors carry.
            # `record_history` writes *through* the page -- it moves
            # `history_complete_from_revid` and reads the head denormalisation
            # -- and a frozen dataclass has neither the columns nor a session
            # to be added to.
            row = session.get(Page, page.pk)
            if row is None:  # pragma: no cover - the upsert just wrote it
                return
            head = head_revision(session, row)
            head_revid = head.revid if head is not None else None
            record_history(
                session, row, [rev for rev in history if rev.revid != head_revid]
            )
    except RemoteIdentityError:
        # Unlike a transient history/API problem, an identity contradiction
        # means continuing could combine two MediaWiki database epochs. Make
        # the parent fetch fail loudly so an operator resets/reconciles the
        # cache instead of trusting a partially corrupt history.
        raise
    except Exception:  # noqa: BLE001 - ordinary enrichment remains best effort
        log.warning("recording history for %s failed", req.title, exc_info=True)


def _materialize_promotion_links(session: Session, page: CachedPage) -> None:
    """Attach fetched target revisions to the source revisions that created them."""
    with write_batch(session):
        target = session.get(Page, page.pk)
        if target is not None:
            materialize_promotion_links(session, target)


def _load_site_snapshot(session: Session, site_pk: int) -> Site:
    with read_snapshot(session):
        site = session.get(Site, site_pk)
        if site is None:
            raise RuntimeError(f"fetch request references missing site {site_pk}")
        return detached_site(site)


def _record_fetch_result(
    session: Session,
    req: ClaimedFetchRequest,
    *,
    status: FetchStatus,
    progress_total: int | None,
    progress_done: int,
    error_message: str | None,
) -> None:
    with write_batch(session):
        db_req = session.get(FetchRequest, req.pk)
        if db_req is None:
            return
        db_req.status = status
        db_req.progress_total = progress_total
        db_req.progress_done = progress_done
        db_req.error_message = error_message
        db_req.updated_at = utcnow()
        session.add(db_req)

        # Propagate completion to the parent (if this is a child request).
        if (
            status in (FetchStatus.done, FetchStatus.error)
            and req.parent_pk is not None
        ):
            _update_parent_progress(session, req.parent_pk)


def _update_parent_progress(session: Session, parent_pk: int) -> None:
    """Increment parent.progress_done; mark done when all children have finished."""
    parent = session.get(FetchRequest, parent_pk)
    if parent is None:
        return
    parent.progress_done = (parent.progress_done or 0) + 1
    if (
        parent.progress_total is not None
        and parent.progress_done >= parent.progress_total
    ):
        parent.status = FetchStatus.done
    parent.updated_at = utcnow()
    session.add(parent)
    # Caller commits.


def _upsert_page(
    session: Session, site: Site, remote: RemotePage, processor: PageProcessor
) -> CachedPage:
    """Write the common Page fields from the remote snapshot, then let the
    type-specific processor enrich its own columns, in one transaction."""
    with write_batch(session):
        page = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == remote.title)
        ).first()
        if page is None:
            page = Page(site_pk=site.pk, title=remote.title)

        # pageid and revid are identities within one MediaWiki database, not
        # merely mutable metadata. Check before overwriting the cached values:
        # a restored wiki paired with a persistent wtbot database otherwise
        # splices two unrelated histories together under this Page row.
        validate_remote_identity(session, page, remote)

        page.namespace_key = remote.namespace_key
        page.namespace_role = role_for_canonical(remote.namespace_canonical or "")
        page.content_model = remote.content_model
        page.text = remote.text
        page.pageid = remote.pageid
        page.revid = remote.revid
        page.remote_timestamp = remote.timestamp
        page.contributor = remote.user
        page.comment = remote.comment

        processor.enrich(page, remote)

        page.dirty = False
        page.fetch_status = FetchState.done
        page.fetch_error = None

        session.add(page)
        session.flush()
        if page.pk is None:
            raise RuntimeError(f"page {remote.title!r} did not get a primary key")

        # The fetch worker is the only writer of the revision store; the head
        # columns above stay as the denormalisation of what this records.
        record_head_revision(session, page, remote)

        meta = session.exec(select(PageMeta).where(PageMeta.page_pk == page.pk)).first()
        target = meta if meta is not None else PageMeta(page_pk=page.pk)
        if processor.enrich_meta(target, remote) and meta is None:
            session.add(target)

        return CachedPage(
            pk=page.pk,
            title=page.title,
            namespace_role=page.namespace_role,
            content_model=page.content_model,
            text=page.text,
        )
