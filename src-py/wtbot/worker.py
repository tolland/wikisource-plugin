from collections.abc import Callable
from pathlib import Path

from sqlmodel import Session, select

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
from wtbot.revision_store import record_head_revision
from wtbot.settings import WikiSettings
from wtbot.timeutil import utcnow
from wtbot.wiki.client import WikiClient, get_wiki_client
from wtbot.wiki.namespaces import sync_namespaces
from wtbot.wiki.wiki_types import PageNotFound, RemotePage

"""Fetch worker: drains the FetchRequest queue, calls the wiki, writes results
back into the cache.

The worker owns the queue mechanics — claim, common Page upsert, progress
bookkeeping. Everything type-specific (blobs, index fan-out, scan-image
metadata) lives in ``wtbot.page_processors``, one class per page type.

Kept as plain functions over a Session + a client factory so it is fully
testable with FakeWikiClient and reusable from either the API (inline, today)
or a future background loop / ``wtbot worker`` command.
"""

ClientFactory = Callable[[Site], WikiClient]


def make_client_for_site(site: Site) -> WikiClient:
    return get_wiki_client(WikiSettings.from_site(site))


def run_pending(
    session: Session,
    client_factory: ClientFactory,
    *,
    limit: int = 100,
    blob_root: Path | None = None,
) -> int:
    """Process up to ``limit`` pending requests. Returns how many were handled."""
    handled = 0
    while handled < limit:
        req = _claim_next(session)
        if req is None:
            break
        _process(session, req, client_factory, blob_root=blob_root)
        handled += 1
    return handled


def _claim_next(session: Session) -> ClaimedFetchRequest | None:
    try:
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
    finally:
        # The worker must not carry an open transaction into pywikibot
        # network calls.
        session.rollback()


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
    )


def _maybe_sync_namespaces(session: Session, site: Site, client: WikiClient) -> None:
    """Sync siteinfo namespaces on first use of a site (no-op on subsequent calls)."""
    from wtbot.model import Namespace

    try:
        already = session.exec(
            select(Namespace).where(Namespace.site_pk == site.pk)
        ).first()
    finally:
        session.rollback()
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
) -> None:
    site = _load_site_snapshot(session, req.site_pk)
    status = FetchStatus.error
    progress_total = None
    progress_done = 0
    error_message = None
    try:
        client = client_factory(site)
        _maybe_sync_namespaces(session, site, client)
        # with vcr.use_cassette("fixtures/vcr_cassettes/fetch-worker.yaml"):
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
        )
        outcome = processor.postprocess(ctx, page, remote)
        status = outcome.status
        progress_total = outcome.progress_total
        progress_done = outcome.progress_done
    except PageNotFound:
        error_message = f"page not found: {req.title}"
    except Exception as exc:  # noqa: BLE001 - record any failure on the row
        error_message = f"{type(exc).__name__}: {exc}"

    _record_fetch_result(
        session,
        req,
        status=status,
        progress_total=progress_total,
        progress_done=progress_done,
        error_message=error_message,
    )


def _load_site_snapshot(session: Session, site_pk: int) -> Site:
    try:
        site = session.get(Site, site_pk)
        if site is None:
            raise RuntimeError(f"fetch request references missing site {site_pk}")
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
    finally:
        session.rollback()


def _record_fetch_result(
    session: Session,
    req: ClaimedFetchRequest,
    *,
    status: FetchStatus,
    progress_total: int | None,
    progress_done: int,
    error_message: str | None,
) -> None:
    try:
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

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.rollback()


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
    try:
        page = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == remote.title)
        ).first()
        if page is None:
            page = Page(site_pk=site.pk, title=remote.title)

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

        cached = CachedPage(
            pk=page.pk,
            title=page.title,
            namespace_role=page.namespace_role,
            content_model=page.content_model,
            text=page.text,
        )
        session.commit()
        return cached
    except Exception:
        session.rollback()
        raise
    finally:
        session.rollback()
