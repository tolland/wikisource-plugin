from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.model import Content, NsRole, Revision, Site, Slot, Title, WikiPage

router = APIRouter(prefix="/pages", tags=["pages"], route_class=DebugLoggingRoute)


class PageQuerySlot(BaseModel):
    role: str
    origin_revid: int | None
    content: Content


class PageQueryRevision(BaseModel):
    revision: Revision
    slots: list[PageQuerySlot]


class PageQueryResult(BaseModel):
    page: Title
    site_label: str | None
    revisions: list[PageQueryRevision]


@router.get("/", response_model=list[Title])
def list_pages(
    session: Session = Depends(get_session),
    site_pk: int | None = None,
    namespace_role: NsRole | None = None,
    content_model: str | None = None,
    title: str | None = None,
    title_contains: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[Title]:
    statement = select(Title).order_by(Title.title).offset(offset).limit(limit)
    if site_pk is not None:
        statement = statement.where(Title.site_pk == site_pk)
    if namespace_role is not None:
        statement = statement.where(Title.namespace_role == namespace_role)
    if content_model is not None:
        statement = statement.join(WikiPage, WikiPage.title_pk == Title.pk).where(
            WikiPage.content_model == content_model
        )
    if title is not None:
        statement = statement.where(Title.title == title)
    if title_contains:
        statement = statement.where(Title.title.contains(title_contains))
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
    addresses ``Title.revid`` (the cached head), just like the other arguments
    address Title columns; the returned history then shows every sparse
    Revision row currently held behind that page.
    """
    statement = (
        select(Title, Site.label)
        .join(Site, Site.pk == Title.site_pk)
        .order_by(Site.label, Title.title, Title.pk)
        .limit(limit)
    )
    if any(v is not None for v in (pageid, revid, content_model)):
        statement = statement.join(WikiPage, WikiPage.title_pk == Title.pk)
        if revid is not None:
            statement = statement.join(
                Revision, Revision.pk == WikiPage.latest_revision_pk
            ).where(Revision.revid == revid)

    filters = (
        (pk, Title.pk),
        (title, Title.title),
        (pageid, WikiPage.pageid),
        (site_label, Site.label),
        (namespace_role, Title.namespace_role),
        (content_model, WikiPage.content_model),
    )
    for value, column in filters:
        if value is not None:
            statement = statement.where(column == value)
    if title_contains:
        statement = statement.where(Title.title.contains(title_contains))

    page_rows = list(session.exec(statement).all())
    if not page_rows:
        return []

    page_pks = [page.pk for page, _ in page_rows if page.pk is not None]
    revision_rows = session.exec(
        select(Revision, Slot, Content)
        .outerjoin(Slot, Slot.revision_pk == Revision.pk)
        .outerjoin(Content, Content.pk == Slot.content_pk)
        .where(Revision.title_pk.in_(page_pks))
        .order_by(Revision.title_pk, Revision.revid.desc(), Slot.role)
    ).all()

    revisions_by_page: dict[int, list[PageQueryRevision]] = {
        title_pk: [] for title_pk in page_pks
    }
    revisions_by_pk: dict[int, PageQueryRevision] = {}
    for revision, slot, content in revision_rows:
        if revision.pk is None:
            continue
        result_revision = revisions_by_pk.get(revision.pk)
        if result_revision is None:
            result_revision = PageQueryRevision(revision=revision, slots=[])
            revisions_by_pk[revision.pk] = result_revision
            revisions_by_page[revision.title_pk].append(result_revision)
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


@router.get("/{title_pk}", response_model=Title)
def get_page(title_pk: int, session: Session = Depends(get_session)) -> Title:
    page = session.get(Title, title_pk)
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    return page
