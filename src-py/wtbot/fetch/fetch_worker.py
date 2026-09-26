import logging
from collections.abc import Callable
from pathlib import Path

from sqlmodel import Session, select

from wtbot.db_session import detached_site, read_snapshot, write_batch
from wtbot.fetch.revision_store import (
    RemoteIdentityError,
    head_revision,
    record_head_revision,
    record_history,
    validate_remote_identity,
)
from wtbot.fetch.utils import _claim_batch, _maybe_sync_namespaces
from wtbot.log.failure_log import FailureContext, record_failure, site_label
from wtbot.log.fetch_log import activity, fetch_context, fetch_stage
from wtbot.model import (
    FetchRequest,
    FetchState,
    FetchStatus,
    Page,
    Site,
    Title,
)
from wtbot.model.wikisource.proofread_page_meta import ProofreadPageMeta
from wtbot.page_processors import (
    CachedPage,
    ClaimedFetchRequest,
    PageProcessor,
    ProcessContext,
    ensure_index_title,
    processor_for,
    proofread_index_identity,
)
from wtbot.promotion.promotion_store import materialize_promotion_links
from wtbot.timeutil import utcnow
from wtbot.title_store import ensure_title, record_fetched_content_model
from wtbot.wiki.client import WikiClient
from wtbot.wiki.failures import FailureKind, WikiFailure
from wtbot.wiki.wiki_types import PageNotFound, RemotePage, RemotePageImages

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
    image_cache: dict[int, dict[str, RemotePageImages | None]] | None = None,
) -> int:
    """Process up to ``limit`` pending requests. Returns how many were handled.

    ``image_cache`` is shared enrichment fetched in bulk (see
    ``page_processors``): an Index fan-out fills it for its children, and each
    child reads its own entry instead of asking the wiki again. Passing None
    uses a cache local to this call. Caches are separated by site so identical
    titles on different wikis cannot share scan metadata.
    """
    if image_cache is None:
        image_cache = {}
    handled = 0
    rate_limited = False

    def observe(failure: WikiFailure) -> None:
        nonlocal rate_limited
        rate_limited |= failure.kind is FailureKind.rate_limited
        if on_failure is not None:
            on_failure(failure)

    while handled < limit:
        requests = _claim_batch(session, min(50, limit - handled))
        if not requests:
            break
        with fetch_stage("load_site"):
            site = _load_site_snapshot(session, requests[0].site_pk)
        client = None
        try:
            client = client_factory(site)
            _maybe_sync_namespaces(session, site, client)
            with fetch_stage("get_pages", f"site_pk={site.pk} titles={len(requests)}"):
                fetched = client.get_pages([req.title for req in requests])
            if [item.title for item in fetched] != [req.title for req in requests]:
                raise ValueError("batch results must match requested titles in order")
            results = [item.result for item in fetched]
        except Exception as exc:
            # A failed batch is not retried as fifty individual API requests.
            results = [exc] * len(requests)

        site_images = image_cache.setdefault(requests[0].site_pk, {})
        image_titles = list(
            dict.fromkeys(
                result.title
                for result in results
                if isinstance(result, RemotePage)
                and result.content_model == "proofread-page"
                and result.title not in site_images
            )
        )
        if client is not None and image_titles:
            try:
                images = client.get_page_images_bulk(image_titles)
                site_images.update((title, images.get(title)) for title in image_titles)
            except Exception:
                log.warning("batch image enrichment failed", exc_info=True)
        for index, (req, result) in enumerate(zip(requests, results, strict=True)):
            with fetch_context(req.pk, req.site_pk, req.title), fetch_stage("request"):
                _process(
                    session,
                    req,
                    site,
                    client,
                    result,
                    blob_root=blob_root,
                    on_failure=observe,
                    image_cache=site_images,
                )
            handled += 1
            if rate_limited:
                # These rows have not been processed. Leave them available to
                # the next drain rather than stranded in_progress.
                with write_batch(session):
                    for remaining in requests[index + 1 :]:
                        row = session.get(FetchRequest, remaining.pk)
                        if row is not None and row.status == FetchStatus.in_progress:
                            row.status = FetchStatus.pending
                            row.updated_at = utcnow()
                            session.add(row)
                return handled
    return handled


def _process(
    session: Session,
    req: ClaimedFetchRequest,
    site: Site,
    client: WikiClient | None,
    result: RemotePage | Exception,
    *,
    blob_root: Path | None = None,
    on_failure: FailureObserver | None = None,
    image_cache: dict[str, RemotePageImages | None] | None = None,
) -> None:
    activity(
        "claimed parent_pk=%s kind=%s depth=%d revisions=%d",
        req.parent_pk,
        req.kind.value,
        req.depth,
        req.revisions,
    )
    activity("site=%s", site_label(site))
    status = FetchStatus.error
    progress_total = None
    progress_done = 0
    error_message = None
    try:
        if isinstance(result, Exception):
            raise result
        if client is None:
            raise RuntimeError("batch returned a page without a wiki client")
        remote = result

        # Drive behaviour from what was actually fetched, not from req.kind.
        processor = processor_for(remote)

        with fetch_stage("store_page"):
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
            with fetch_stage("revision_history"):
                _record_history(session, client, page, req)

        with fetch_stage("promotion_links"):
            _materialize_promotion_links(session, page)

        with fetch_stage("postprocess"):
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

    with fetch_stage("store_result"):
        _record_fetch_result(
            session,
            req,
            status=status,
            progress_total=progress_total,
            progress_done=progress_done,
            error_message=error_message,
        )

    activity(
        "result status=%s progress=%s/%s error=%s",
        status.value,
        progress_done,
        progress_total,
        error_message,
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
        with fetch_stage("get_history", f"limit={req.revisions}"):
            history = client.get_history(req.title, limit=req.revisions)
        activity("history received revisions=%d", len(history) if history else 0)
    except Exception as exc:  # noqa: BLE001 - enrichment must not fail a fetch
        activity("history enrichment skipped: %s", exc)
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
        activity("history storage failed; continuing with head revision")
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
    activity(
        "parent request_pk=%d status=%s progress=%s/%s (awaiting commit)",
        parent_pk,
        parent.status.value,
        parent.progress_done,
        parent.progress_total,
    )
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
        # The wiki has now said what this title is. A new title records that
        # as its expectation; an existing one gets its earlier guess checked.
        # An existing page reaches its title through the shared pk, not by
        # matching the string again.
        if page is None:
            title_row = ensure_title(
                session,
                site_pk=site.pk,
                title=remote.title,
                expected_content_model=remote.content_model,
            )
            page = Page(pk=title_row.pk, site_pk=site.pk, title=remote.title)
        else:
            title_row = session.get(Title, page.pk)

        record_fetched_content_model(session, title_row, remote.content_model)

        # pageid and revid are identities within one MediaWiki database, not
        # merely mutable metadata. Check before overwriting the cached values:
        # a restored wiki paired with a persistent wtbot database otherwise
        # splices two unrelated histories together under this Page row.
        validate_remote_identity(session, page, remote)

        page.content_model = remote.content_model
        page.text = remote.text
        page.pageid = remote.pageid
        page.revid = remote.revid
        page.remote_timestamp = remote.timestamp
        page.contributor = remote.user
        page.comment = remote.comment

        processor.enrich(page, remote)

        title_row.namespace_key = remote.namespace_key
        title_row.dirty = False
        title_row.fetch_status = FetchState.done
        session.add(title_row)

        session.add(page)
        session.flush()
        if page.pk is None:
            raise RuntimeError(f"page {remote.title!r} did not get a primary key")

        # The fetch worker is the only writer of the revision store; the head
        # columns above stay as the denormalisation of what this records.
        record_head_revision(session, page, remote)

        identity = proofread_index_identity(remote.title)
        if remote.content_model == "proofread-page" and identity is not None:
            index_title, page_number = identity
            index_page = ensure_index_title(session, site.pk, index_title)
            meta = session.get(ProofreadPageMeta, page.pk)
            target = meta or ProofreadPageMeta(
                title_pk=page.pk,
                index_title_pk=index_page.pk,
            )
            target.index_title_pk = index_page.pk
            target.page_number = page_number
            session.add(target)

        return CachedPage(
            pk=page.pk,
            title=page.title,
            content_model=page.content_model,
            text=page.text,
        )
