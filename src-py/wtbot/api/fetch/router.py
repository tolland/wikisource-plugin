from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.api.fetch.model import (
    DrainRequest,
    DrainResponse,
    FetchCreate,
    QueueStatsResponse,
    RefreshCreate,
    RefreshPlanOut,
    RefreshResult,
)
from wtbot.deps import get_session
from wtbot.fetch.queue_runner import (
    drain_queue,
    queue_stats,
)
from wtbot.incremental import RefreshBasis, RefreshPlan, plan_refresh
from wtbot.model import FetchKind, FetchRequest, Page
from wtbot.site_store import require_credentialed_site

"""Cache-fill endpoint (surface B).

The plugin/CLI POST a fetch request naming a registered site by label; we
enqueue a FetchRequest against it. Draining that queue -- the worker making the wiki calls and
writing pages back to SQLite -- is a *separate* operation: ``POST /fetch/drain``
or ``wtbot drain``.

Enqueue used to drain inline, which made one HTTP call mean "fetch this entire
book, now, before I answer". That is untenable against a wiki that rate-limits
us: fetching an Index is hundreds of throttled requests, and the correct
response to a 429 -- going slower -- makes the caller's wait longer rather than
shorter. Splitting them means the throttle can be whatever the wiki demands,
and progress is observed by polling ``GET /fetch/{pk}`` or ``GET /fetch/queue``
instead of by holding a socket open.

Sites are addressed by ``label`` and are never created here. Taking
family/code/api_url per request meant a typo registered a new wiki -- with no
credentials -- and fetched from it anonymously; the first sign was a log line
saying so, long after the fact. Registration is its own deliberate step
(``POST /sites`` / ``wtbot site add``), where credentials can be attached.
"""

router = APIRouter(
    prefix="/fetch",
    tags=["fetch"],
    route_class=DebugLoggingRoute,
)


@router.post("/", status_code=202)
def create_fetch(payload: FetchCreate, session: Session = Depends(get_session)) -> dict:
    """Enqueue a fetch. Returns immediately; nothing is fetched yet.

    ``page`` is whatever is already cached for the title -- usually null on a
    first fetch, and a *stale* snapshot on a refetch. It is what we hold, not
    what was just fetched: run a drain and re-read to get that.
    """
    site = require_credentialed_site(session, payload.label)

    req = FetchRequest(
        site_pk=site.pk,
        title=payload.title,
        kind=payload.kind,
        depth=payload.depth,
        revisions=payload.revisions,
    )
    session.add(req)
    session.commit()
    session.refresh(req)

    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == payload.title)
    ).first()
    return {"request": req, "page": page}


@router.post("/drain", response_model=DrainResponse)
def drain(
    request: Request,
    payload: DrainRequest | None = None,
    session: Session = Depends(get_session),
) -> DrainResponse:
    """Work the queue until it is empty, then report what happened.

    This is the call that talks to the wiki, and every request it makes is
    throttled to stay inside the rate limit, so draining a freshly fanned-out
    book takes minutes. Call it from a job, from ``wtbot drain``, or from
    anything that can wait -- not from something holding a UI open.
    """
    payload = payload or DrainRequest()
    result = drain_queue(
        session,
        request.app.state.client_factory,
        blob_root=getattr(request.app.state, "blob_root", None),
        batch=payload.batch,
        max_passes=payload.max_passes,
    )
    return DrainResponse(
        handled=result.handled,
        passes=result.passes,
        remaining=result.remaining,
        stop_reason=result.stop_reason,
        complete=result.complete,
        retry_after=result.retry_after,
    )


@router.get("/queue", response_model=QueueStatsResponse)
def get_queue(session: Session = Depends(get_session)) -> QueueStatsResponse:
    """Queue depth without draining it -- how a caller watches progress."""
    stats = queue_stats(session)
    return QueueStatsResponse(
        counts=stats.counts,
        pending=stats.pending,
        total=stats.total,
        oldest_pending_at=stats.oldest_pending_at,
    )


@router.post("/refresh", status_code=202, response_model=RefreshResult)
def refresh(
    payload: RefreshCreate,
    request: Request,
    session: Session = Depends(get_session),
) -> RefreshResult:
    """Refetch only what moved, via ``list=recentchanges``.

    Not a second fetch mechanism -- it produces a shorter list of titles and
    hands them to the same queue and worker as ``POST /fetch``. The response
    says which *basis* the list came from: a caller that cannot tell an
    incremental plan from a full one cannot tell "two pages moved" from "we
    could not tell, so here is everything".

    The watermark advances only after the fetches are enqueued, and only on an
    incremental plan. Advancing it on a full pass would claim a position in a
    change stream we did not read.

    Like ``POST /fetch``, this enqueues without fetching: ``enqueued`` is a
    count of queued work, not of pages written. Drain to make it real.
    """
    site = require_credentialed_site(session, payload.label)
    factory = request.app.state.client_factory
    plan = plan_refresh(
        session,
        site,
        factory(site),
        since=payload.since,
        title_prefix=payload.title_prefix,
    )

    if payload.dry_run:
        return RefreshResult(plan=_plan_summary(plan), enqueued=0)

    for title in plan.titles:
        session.add(FetchRequest(site_pk=site.pk, title=title, kind=FetchKind.single))
    session.commit()

    # Enqueued, not fetched -- same split as POST /fetch. The watermark still
    # advances here: it records how far the *change stream* was read, which
    # this call did do, and the enqueued titles survive a crash in the queue.
    if plan.basis is RefreshBasis.incremental and plan.watermark is not None:
        site.changes_seen_through = plan.watermark
        session.add(site)
        session.commit()
        session.refresh(site)

    return RefreshResult(
        plan=_plan_summary(plan),
        enqueued=len(plan.titles),
        watermark=site.changes_seen_through,
    )


def _plan_summary(plan: RefreshPlan) -> RefreshPlanOut:
    return RefreshPlanOut(
        basis=plan.basis,
        reason=plan.reason,
        titles=list(plan.titles),
        watermark=plan.watermark,
        changes=len(plan.changes),
    )


@router.get("/{pk}", response_model=FetchRequest)
def get_fetch(pk: int, session: Session = Depends(get_session)) -> FetchRequest:
    req = session.get(FetchRequest, pk)
    if req is None:
        raise HTTPException(status_code=404, detail="fetch request not found")
    return req
