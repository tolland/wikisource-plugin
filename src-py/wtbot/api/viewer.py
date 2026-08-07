from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.model import IndexMeta, Page

router = APIRouter(prefix="/viewer", tags=["viewer"], route_class=DebugLoggingRoute)

PROOFREAD_INDEX_CONTENT_MODEL = "proofread-index"


class IndexPageSummary(BaseModel):
    pk: int
    title: str
    page_count: int | None = None
    revid: int | None = None
    content_model: str | None = None
    body_length: int


class IndexPageDetail(IndexPageSummary):
    body: str


def _summary(page: Page, page_count: int | None) -> IndexPageSummary:
    return IndexPageSummary(
        pk=page.pk or 0,
        title=page.title,
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
    return [_summary(page, counts.get(page.pk)) for page in pages]


@router.get("/indexes/{page_pk}", response_model=IndexPageDetail)
def get_index_page(
    page_pk: int, session: Session = Depends(get_session)
) -> IndexPageDetail:
    page = session.get(Page, page_pk)
    if page is None or page.content_model != PROOFREAD_INDEX_CONTENT_MODEL:
        raise HTTPException(status_code=404, detail="index page not found")

    page_count = _page_counts(session, [page.pk]).get(page.pk)
    summary = _summary(page, page_count)
    return IndexPageDetail(**summary.model_dump(), body=page.text or "")


def _page_counts(session: Session, page_pks: list[int]) -> dict[int, int | None]:
    """Index page_count now lives on IndexMeta; look it up per Index page_pk."""
    if not page_pks:
        return {}
    rows = session.exec(select(IndexMeta).where(IndexMeta.page_pk.in_(page_pks))).all()
    return {row.page_pk: row.page_count for row in rows}
