from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from wtbot.deps import get_session
from wtbot.model import (
    FileMeta,
    FileOrigin,
    IndexMeta,
    NsRole,
    Page,
    PageMeta,
)
from wtbot.model.page_meta import SHORT_NAME_RE
from wtbot.vfs.nodes import (
    FileBlobLeaf,
    FileDir,
    FileWikitext,
    IndexAssetLeaf,
    IndexDir,
    IndexWikitext,
    PageLeaf,
    resolve,
)
from wtbot.vfs.store import PROOFREAD_INDEX_CONTENT_MODEL, PageStore

"""Per-role Page metadata extensions (IndexMeta / PageMeta / FileMeta).

GET returns 404 while no row exists; PUT upserts with partial-update
semantics (only fields present in the request body are applied).
POST /index-meta/ensure is the fetch-or-create used by flows that need a
short_name to exist (generated image names) without the client having to
derive the default itself.
"""

router = APIRouter(prefix="/pages", tags=["page-meta"])


@router.get("/resolve", response_model=Page)
def resolve_page(
    path: str | None = Query(
        None, description="wikisource:// VFS path, resolved via the overlay"
    ),
    family: str | None = Query(None),
    code: str | None = Query(None),
    title: str | None = Query(None, description="full title incl. namespace prefix"),
    session: Session = Depends(get_session),
) -> Page:
    """Identity bridge between the two addressing schemes and the rich model:
    map either a wikisource:// VFS path (what the client's editors/tree hold)
    or a canonical (family, code, title) triple (what batch tooling holds) to
    the backing Page row — whose pk keys the per-role metadata endpoints."""
    store = PageStore(session)
    if path is not None:
        match resolve(store, path):
            case PageLeaf(_, _, page) | IndexAssetLeaf(_, _, page, _):
                return page
            case IndexDir(_, _, index) | IndexWikitext(_, _, index):
                return index
            case (
                FileDir(_, _, file_page)
                | FileWikitext(_, _, file_page)
                | FileBlobLeaf(_, _, file_page)
            ):
                return file_page
            case _:
                raise HTTPException(
                    status_code=404, detail=f"no page behind path: {path}"
                )
    if family is not None and code is not None and title is not None:
        site = store.site(family, code)
        page = store.page(site, title) if site is not None else None
        if page is None:
            raise HTTPException(
                status_code=404, detail=f"page not found: {family}/{code}/{title}"
            )
        return page
    raise HTTPException(
        status_code=400, detail="pass either ?path= or ?family=&code=&title="
    )


def _get_page(session: Session, page_pk: int) -> Page:
    page = session.get(Page, page_pk)
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    return page


class IndexMetaUpdate(BaseModel):
    short_name: str


class PageMetaUpdate(BaseModel):
    source_image_url: str | None = None
    thumb_url: str | None = None
    thumb_width: int | None = None
    thumb_height: int | None = None
    raster_path: str | None = None
    thumb_path: str | None = None


class FileMetaUpdate(BaseModel):
    origin: FileOrigin | None = None
    source_page_pk: int | None = None
    source_page_number: int | None = None
    crop_x: int | None = None
    crop_y: int | None = None
    crop_w: int | None = None
    crop_h: int | None = None


# -- IndexMeta ---------------------------------------------------------------


def _require_index_page(session: Session, page_pk: int) -> Page:
    page = _get_page(session, page_pk)
    if page.content_model != PROOFREAD_INDEX_CONTENT_MODEL:
        raise HTTPException(
            status_code=400, detail=f"not a ProofreadPage index: {page.title}"
        )
    return page


@router.get("/{page_pk}/index-meta", response_model=IndexMeta)
def get_index_meta(page_pk: int, session: Session = Depends(get_session)) -> IndexMeta:
    page = _require_index_page(session, page_pk)
    meta = PageStore(session).index_meta(page)
    if meta is None:
        raise HTTPException(status_code=404, detail="no index meta yet")
    return meta


@router.post("/{page_pk}/index-meta/ensure", response_model=IndexMeta)
def ensure_index_meta(
    page_pk: int, session: Session = Depends(get_session)
) -> IndexMeta:
    page = _require_index_page(session, page_pk)
    return PageStore(session).ensure_index_meta(page)


@router.put("/{page_pk}/index-meta", response_model=IndexMeta)
def put_index_meta(
    page_pk: int,
    update: IndexMetaUpdate,
    session: Session = Depends(get_session),
) -> IndexMeta:
    page = _require_index_page(session, page_pk)
    if not SHORT_NAME_RE.match(update.short_name):
        raise HTTPException(
            status_code=400,
            detail="short_name must be filename-safe: letters, digits, '_', '-'",
        )
    store = PageStore(session)
    meta = store.index_meta(page)
    if (
        meta is None or meta.short_name != update.short_name
    ) and store.short_name_taken(page.site_pk, update.short_name):
        raise HTTPException(
            status_code=409,
            detail=f"short_name already in use on this site: {update.short_name}",
        )
    if meta is None:
        meta = IndexMeta(
            page_pk=page.pk, site_pk=page.site_pk, short_name=update.short_name
        )
    else:
        meta.short_name = update.short_name
    session.add(meta)
    session.commit()
    session.refresh(meta)
    return meta


# -- PageMeta ------------------------------------------------------------------


@router.get("/{page_pk}/page-meta", response_model=PageMeta)
def get_page_meta(page_pk: int, session: Session = Depends(get_session)) -> PageMeta:
    page = _get_page(session, page_pk)
    meta = PageStore(session).page_meta(page)
    if meta is None:
        raise HTTPException(status_code=404, detail="no page meta yet")
    return meta


@router.put("/{page_pk}/page-meta", response_model=PageMeta)
def put_page_meta(
    page_pk: int,
    update: PageMetaUpdate,
    session: Session = Depends(get_session),
) -> PageMeta:
    page = _get_page(session, page_pk)
    if page.namespace_role != NsRole.page:
        raise HTTPException(
            status_code=400, detail=f"not a Page:-namespace page: {page.title}"
        )
    meta = PageStore(session).page_meta(page) or PageMeta(page_pk=page.pk)
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(meta, field, value)
    session.add(meta)
    session.commit()
    session.refresh(meta)
    return meta


# -- FileMeta ------------------------------------------------------------------


@router.get("/{page_pk}/file-meta", response_model=FileMeta)
def get_file_meta(page_pk: int, session: Session = Depends(get_session)) -> FileMeta:
    page = _get_page(session, page_pk)
    meta = PageStore(session).file_meta(page)
    if meta is None:
        raise HTTPException(status_code=404, detail="no file meta yet")
    return meta


@router.put("/{page_pk}/file-meta", response_model=FileMeta)
def put_file_meta(
    page_pk: int,
    update: FileMetaUpdate,
    session: Session = Depends(get_session),
) -> FileMeta:
    page = _get_page(session, page_pk)
    if page.namespace_role != NsRole.file:
        raise HTTPException(
            status_code=400, detail=f"not a File:-namespace page: {page.title}"
        )
    meta = PageStore(session).file_meta(page) or FileMeta(page_pk=page.pk)
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(meta, field, value)
    session.add(meta)
    session.commit()
    session.refresh(meta)
    return meta
