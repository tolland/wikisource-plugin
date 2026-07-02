from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.model import Page

router = APIRouter(prefix="/viewer", tags=["viewer"])

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


def _summary(page: Page) -> IndexPageSummary:
    return IndexPageSummary(
        pk=page.pk or 0,
        title=page.title,
        page_count=page.page_count,
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
    return [_summary(page) for page in pages]


@router.get("/indexes/{page_pk}", response_model=IndexPageDetail)
def get_index_page(
    page_pk: int, session: Session = Depends(get_session)
) -> IndexPageDetail:
    page = session.get(Page, page_pk)
    if page is None or page.content_model != PROOFREAD_INDEX_CONTENT_MODEL:
        raise HTTPException(status_code=404, detail="index page not found")

    summary = _summary(page)
    return IndexPageDetail(**summary.model_dump(), body=page.text or "")
