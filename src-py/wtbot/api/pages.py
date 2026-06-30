from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.sqlmodel import NsRole, Page

router = APIRouter(prefix="/pages", tags=["pages"])


@router.get("/", response_model=list[Page])
def list_pages(
    session: Session = Depends(get_session),
    site_pk: int | None = None,
    namespace_role: NsRole | None = None,
    content_model: str | None = None,
    title: str | None = None,
    title_contains: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[Page]:
    statement = select(Page).order_by(Page.title).offset(offset).limit(limit)
    if site_pk is not None:
        statement = statement.where(Page.site_pk == site_pk)
    if namespace_role is not None:
        statement = statement.where(Page.namespace_role == namespace_role)
    if content_model is not None:
        statement = statement.where(Page.content_model == content_model)
    if title is not None:
        statement = statement.where(Page.title == title)
    if title_contains:
        statement = statement.where(Page.title.contains(title_contains))
    return list(session.exec(statement).all())


@router.get("/{page_pk}", response_model=Page)
def get_page(page_pk: int, session: Session = Depends(get_session)) -> Page:
    page = session.get(Page, page_pk)
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    return page
