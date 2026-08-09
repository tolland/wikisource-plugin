from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.model import IndexMeta, Page, Site

router = APIRouter(prefix="/viewer", tags=["viewer"], route_class=DebugLoggingRoute)

PROOFREAD_INDEX_CONTENT_MODEL = "proofread-index"


class IndexPageSummary(BaseModel):
    pk: int
    title: str
    # Site the Index belongs to -- exposed so the client can build the
    # wikisource:// VFS path (/{family}/{code}/{title}) other APIs (page-nav,
    # locator-index, ...) key off, without a second round trip.
    family: str
    code: str
    page_count: int | None = None
    revid: int | None = None
    content_model: str | None = None
    body_length: int


class IndexPageDetail(IndexPageSummary):
    body: str


def _summary(page: Page, site: Site, page_count: int | None) -> IndexPageSummary:
    return IndexPageSummary(
        pk=page.pk or 0,
        title=page.title,
        family=site.family,
        code=site.code,
        page_count=page_count,
        revid=page.revid,
        content_model=page.content_model,
        body_length=len(page.text or ""),
    )


@router.get("/indexes", response_model=list[IndexPageSummary])
def list_index_pages(session: Session = Depends(get_session)) -> list[IndexPageSummary]:
    pages = session.exec(
        select(Page)
        .where(Page.content_model == PROOFREAD_INDEX_CONTENT_MODEL)
        .order_by(Page.title)
    ).all()
    counts = _page_counts(session, [p.pk for p in pages if p.pk is not None])
    sites = _sites_by_pk(session, [p.site_pk for p in pages])
    return [_summary(page, sites[page.site_pk], counts.get(page.pk)) for page in pages]


@router.get("/indexes/{page_pk}", response_model=IndexPageDetail)
def get_index_page(
    page_pk: int, session: Session = Depends(get_session)
) -> IndexPageDetail:
    page = session.get(Page, page_pk)
    if page is None or page.content_model != PROOFREAD_INDEX_CONTENT_MODEL:
        raise HTTPException(status_code=404, detail="index page not found")

    page_count = _page_counts(session, [page.pk]).get(page.pk)
    site = _sites_by_pk(session, [page.site_pk])[page.site_pk]
    summary = _summary(page, site, page_count)
    return IndexPageDetail(**summary.model_dump(), body=page.text or "")


def _sites_by_pk(session: Session, site_pks: list[int]) -> dict[int, Site]:
    if not site_pks:
        return {}
    rows = session.exec(select(Site).where(Site.pk.in_(set(site_pks)))).all()
    return {row.pk: row for row in rows}


def _page_counts(session: Session, page_pks: list[int]) -> dict[int, int | None]:
    """Index page_count now lives on IndexMeta; look it up per Index page_pk."""
    if not page_pks:
        return {}
    rows = session.exec(select(IndexMeta).where(IndexMeta.page_pk.in_(page_pks))).all()
    return {row.page_pk: row.page_count for row in rows}
