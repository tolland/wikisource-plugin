"""Cache-fill endpoint (surface B).

The plugin/CLI POST a fetch request; we upsert the Site, enqueue a FetchRequest,
then drain the queue (inline for now) so the worker makes the wiki call and
writes the page back to SQLite. The response carries the request row plus the
resulting cached page.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.sqlmodel import FetchKind, FetchRequest, Page, Site
from wtbot.worker import run_pending

router = APIRouter(prefix="/fetch", tags=["fetch"])


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
        site_pk=site.pk, title=payload.title, kind=payload.kind, depth=payload.depth
    )
    session.add(req)
    session.commit()
    session.refresh(req)

    # Drain the queue now. The same run_pending will back a background worker later.
    run_pending(session, request.app.state.client_factory, blob_root=request.app.state.blob_root)
    session.refresh(req)

    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == payload.title)
    ).first()
    return {"request": req, "page": page}


@router.get("/{pk}", response_model=FetchRequest)
def get_fetch(pk: int, session: Session = Depends(get_session)) -> FetchRequest:
    req = session.get(FetchRequest, pk)
    if req is None:
        raise HTTPException(status_code=404, detail="fetch request not found")
    return req
