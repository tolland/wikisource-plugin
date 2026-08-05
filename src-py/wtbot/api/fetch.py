"""Cache-fill endpoint (surface B).

The plugin/CLI POST a fetch request; we upsert the Site, enqueue a FetchRequest,
then drain the queue (inline for now) so the worker makes the wiki call and
writes the page back to SQLite. The response carries the request row plus the
resulting cached page.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.incremental import RefreshBasis, RefreshPlan, plan_refresh
from wtbot.model import FetchKind, FetchRequest, Page, Site
from wtbot.worker import run_pending

router = APIRouter(prefix="/fetch", tags=["fetch"])


class RefreshCreate(BaseModel):
    family: str
    code: str
    api_url: str | None = None
    since: datetime | None = None
    """Overrides the site's stored watermark. Mostly for re-running a window."""
    title_prefix: str | None = None
    """Narrow to one work, e.g. 'Page:Foo.djvu/'. recentchanges has no prefix
    filter, so this is applied to the returned metadata."""
    dry_run: bool = False
    """Plan only: report what would be refetched and advance nothing."""


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


@router.post("/refresh", status_code=202)
def refresh(
    payload: RefreshCreate,
    request: Request,
    session: Session = Depends(get_session),
) -> dict:
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
        return {"plan": _plan_summary(plan), "enqueued": 0}

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

    return {
        "plan": _plan_summary(plan),
        "enqueued": len(plan.titles),
        "watermark": site.changes_seen_through,
    }


def _plan_summary(plan: RefreshPlan) -> dict:
    return {
        "basis": plan.basis.value,
        "reason": plan.reason,
        "titles": list(plan.titles),
        "watermark": plan.watermark,
        "changes": len(plan.changes),
    }


@router.get("/{pk}", response_model=FetchRequest)
def get_fetch(pk: int, session: Session = Depends(get_session)) -> FetchRequest:
    req = session.get(FetchRequest, pk)
    if req is None:
        raise HTTPException(status_code=404, detail="fetch request not found")
    return req
