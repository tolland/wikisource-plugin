from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.incremental import RefreshBasis, RefreshPlan, plan_refresh
from wtbot.model import FetchKind, FetchRequest, FetchStatus, Page, Site
from wtbot.queue_runner import (
    DEFAULT_BATCH,
    DEFAULT_MAX_PASSES,
    DrainStop,
    drain_queue,
    queue_stats,
)

from .debug_logging_route import DebugLoggingRoute

"""Cache-fill endpoint (surface B).

The plugin/CLI POST a fetch request; we upsert the Site and enqueue a
FetchRequest. Draining that queue -- the worker making the wiki calls and
writing pages back to SQLite -- is a *separate* operation: ``POST /fetch/drain``
or ``wtbot drain``.

Enqueue used to drain inline, which made one HTTP call mean "fetch this entire
book, now, before I answer". That is untenable against a wiki that rate-limits
us: fetching an Index is hundreds of throttled requests, and the correct
response to a 429 -- going slower -- makes the caller's wait longer rather than
shorter. Splitting them means the throttle can be whatever the wiki demands,
and progress is observed by polling ``GET /fetch/{pk}`` or ``GET /fetch/queue``
instead of by holding a socket open.
"""

router = APIRouter(
    prefix="/fetch",
    tags=["fetch"],
    route_class=DebugLoggingRoute,
)


class RefreshCreate(BaseModel):
    """What to refresh. Field descriptions are ``Field(description=...)`` rather
    than attribute docstrings so they reach the OpenAPI schema -- Pydantic
    ignores the docstring form unless ``use_attribute_docstrings`` is set, and a
    body that renders as an undocumented JSON blob is the thing this fixes."""

    family: str = Field(description="pywikibot family, e.g. 'wikisource'")
    code: str = Field(description="pywikibot language code, e.g. 'en'")
    api_url: str | None = Field(
        default=None,
        description="Full action API endpoint; stored on the Site when given.",
    )
    since: datetime | None = Field(
        default=None,
        description=(
            "Overrides the site's stored watermark. Mostly for re-running a "
            "window that has already been consumed."
        ),
    )
    title_prefix: str | None = Field(
        default=None,
        description=(
            "Narrow to one work, e.g. 'Page:Foo.djvu/'. recentchanges has no "
            "prefix filter -- rctitle takes a single page -- so this is applied "
            "to the returned metadata. With a prefix, titles not held locally "
            "are taken too, which is how a partially transcribed index grows."
        ),
    )
    dry_run: bool = Field(
        default=False,
        description="Plan only: report what would be refetched, advance nothing.",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "family": "wikisource",
                    "code": "en",
                    "title_prefix": "Page:Canadian patent 29537.djvu/",
                    "dry_run": True,
                }
            ]
        }
    }


class RefreshPlanOut(BaseModel):
    """The plan, as reported. ``basis`` is the load-bearing field: a caller that
    cannot tell an incremental plan from a full one cannot tell "two pages
    moved" from "we could not tell, so here is everything"."""

    basis: RefreshBasis = Field(
        description="'incremental' if recentchanges answered; 'full' otherwise."
    )
    reason: str | None = Field(
        default=None,
        description="Why the basis is not incremental, when it is not.",
    )
    titles: list[str] = Field(description="Titles to refetch, deduplicated.")
    watermark: datetime | None = Field(
        default=None,
        description=(
            "Newest change timestamp observed. None on a full plan, which read "
            "no change stream and so may claim no position in one."
        ),
    )
    changes: int = Field(
        description="Raw recentchanges entries behind `titles`; several can "
        "collapse to one title."
    )


class RefreshResult(BaseModel):
    plan: RefreshPlanOut
    enqueued: int = Field(description="FetchRequests created; 0 for a dry run.")
    watermark: datetime | None = Field(
        default=None,
        description="The site's watermark after the run.",
    )


class FetchCreate(BaseModel):
    title: str
    family: str
    code: str
    api_url: str | None = None
    kind: FetchKind = FetchKind.single
    depth: int = 0


class DrainRequest(BaseModel):
    """How much of the queue to work through in this call."""

    batch: int = Field(
        default=DEFAULT_BATCH, ge=1, description="Requests claimed per pass."
    )
    max_passes: int = Field(
        default=DEFAULT_MAX_PASSES,
        ge=1,
        description=(
            "Safety bound on passes. Several are normal -- a fan-out enqueues "
            "children mid-drain -- so this only stops a pathological cycle."
        ),
    )


class DrainResponse(BaseModel):
    handled: int = Field(description="Fetch requests processed in this call.")
    passes: int = Field(description="Claim/process cycles it took.")
    remaining: int = Field(
        description="Requests still pending or in progress afterwards."
    )
    stop_reason: DrainStop = Field(
        description=(
            "'queue_empty' when the queue ran out; 'max_passes' when the bound "
            "was hit first, which leaves work queued."
        )
    )
    complete: bool = Field(description="Queue empty and nothing left behind.")


class QueueStatsResponse(BaseModel):
    """What is in the queue, without draining it."""

    counts: dict[FetchStatus, int] = Field(description="Requests by status.")
    pending: int = Field(description="Requests a drain would pick up now.")
    total: int = Field(description="All requests ever recorded, by status.")
    oldest_pending_at: datetime | None = Field(
        default=None, description="When the oldest pending request was queued."
    )


def _get_or_create_site(
    session: Session, family: str, code: str, api_url: str | None
) -> Site:
    site = session.exec(
        select(Site).where(Site.family == family, Site.code == code)
    ).first()
    if site is None:
        site = Site(family=family, code=code, api_url=api_url)
        session.add(site)
        session.commit()
        session.refresh(site)
    elif api_url and site.api_url != api_url:
        site.api_url = api_url
        session.add(site)
        session.commit()
        session.refresh(site)
    return site


@router.post("/", status_code=202)
def create_fetch(payload: FetchCreate, session: Session = Depends(get_session)) -> dict:
    """Enqueue a fetch. Returns immediately; nothing is fetched yet.

    ``page`` is whatever is already cached for the title -- usually null on a
    first fetch, and a *stale* snapshot on a refetch. It is what we hold, not
    what was just fetched: run a drain and re-read to get that.
    """
    site = _get_or_create_site(session, payload.family, payload.code, payload.api_url)

    req = FetchRequest(
        site_pk=site.pk,
        title=payload.title,
        kind=payload.kind,
        depth=payload.depth,
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
    site = _get_or_create_site(session, payload.family, payload.code, payload.api_url)
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
