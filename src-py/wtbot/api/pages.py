from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.model import Content, NsRole, Page, Revision, Site, Slot

router = APIRouter(prefix="/pages", tags=["pages"], route_class=DebugLoggingRoute)


class PageQuerySlot(BaseModel):
    role: str
    origin_revid: int | None
    content: Content


class PageQueryRevision(BaseModel):
    revision: Revision
    slots: list[PageQuerySlot]


class PageQueryResult(BaseModel):
    page: Page
    site_label: str | None
    revisions: list[PageQueryRevision]


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


@router.get("/query", response_model=list[PageQueryResult])
def query_pages(
    session: Session = Depends(get_session),
    pk: int | None = None,
    title: str | None = None,
    title_contains: str | None = None,
    pageid: int | None = None,
    revid: int | None = None,
    site_label: str | None = None,
    namespace_role: NsRole | None = None,
    content_model: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
) -> list[PageQueryResult]:
    """Find pages and return their complete locally-held revision records.

    Every supplied predicate is combined with AND. ``revid`` deliberately
    addresses ``Page.revid`` (the cached head), just like the other arguments
    address Page columns; the returned history then shows every sparse
    Revision row currently held behind that page.
    """
    statement = (
        select(Page, Site.label)
        .join(Site, Site.pk == Page.site_pk)
        .order_by(Site.label, Page.title, Page.pk)
        .limit(limit)
    )
    filters = (
        (pk, Page.pk),
        (title, Page.title),
        (pageid, Page.pageid),
        (revid, Page.revid),
        (site_label, Site.label),
        (namespace_role, Page.namespace_role),
        (content_model, Page.content_model),
    )
    for value, column in filters:
        if value is not None:
            statement = statement.where(column == value)
    if title_contains:
        statement = statement.where(Page.title.contains(title_contains))

    page_rows = list(session.exec(statement).all())
    if not page_rows:
        return []

    page_pks = [page.pk for page, _ in page_rows if page.pk is not None]
    revision_rows = session.exec(
        select(Revision, Slot, Content)
        .outerjoin(Slot, Slot.revision_pk == Revision.pk)
        .outerjoin(Content, Content.pk == Slot.content_pk)
        .where(Revision.page_pk.in_(page_pks))
        .order_by(Revision.page_pk, Revision.revid.desc(), Slot.role)
    ).all()

    revisions_by_page: dict[int, list[PageQueryRevision]] = {
        page_pk: [] for page_pk in page_pks
    }
    revisions_by_pk: dict[int, PageQueryRevision] = {}
    for revision, slot, content in revision_rows:
        if revision.pk is None:
            continue
        result_revision = revisions_by_pk.get(revision.pk)
        if result_revision is None:
            result_revision = PageQueryRevision(revision=revision, slots=[])
            revisions_by_pk[revision.pk] = result_revision
            revisions_by_page[revision.page_pk].append(result_revision)
        if slot is not None and content is not None:
            result_revision.slots.append(
                PageQuerySlot(
                    role=slot.role,
                    origin_revid=slot.origin_revid,
                    content=content,
                )
            )

    return [
        PageQueryResult(
            page=page,
            site_label=label,
            revisions=revisions_by_page[page.pk],
        )
        for page, label in page_rows
        if page.pk is not None
    ]


@router.get("/{page_pk}", response_model=Page)
def get_page(page_pk: int, session: Session = Depends(get_session)) -> Page:
    page = session.get(Page, page_pk)
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    return page
