from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.incremental import RefreshBasis, RefreshPlan, plan_refresh
from wtbot.model import FetchKind, FetchRequest, Page, Site
from wtbot.worker import run_pending

from .debug_logging_route import DebugLoggingRoute

"""Cache-fill endpoint (surface B).

The plugin/CLI POST a fetch request; we upsert the Site, enqueue a FetchRequest,
then drain the queue (inline for now) so the worker makes the wiki call and
writes the page back to SQLite. The response carries the request row plus the
resulting cached page.
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
def create_fetch(
    payload: FetchCreate, request: Request, session: Session = Depends(get_session)
) -> dict:
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

    # Drain the queue until empty (inline for now; a background worker replaces
    # this loop later).  A single run_pending(limit=100) is not enough when an
    # Index: fans out to hundreds of Page: children.
    factory = request.app.state.client_factory
    blob_root = request.app.state.blob_root
    while run_pending(session, factory, blob_root=blob_root, limit=200) > 0:
        pass  # keep draining until nothing is left pending
    session.refresh(req)

    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == payload.title)
    ).first()
    return {"request": req, "page": page}


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

    blob_root = request.app.state.blob_root
    while run_pending(session, factory, blob_root=blob_root, limit=200) > 0:
        pass

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
