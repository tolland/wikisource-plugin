from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.model.wikisource.proofread_page_meta import ProofreadPageMeta
from wtbot.vfs.nodes import ProofreadPageRef, proofread_page_of, resolve
from wtbot.vfs.store import Entry, PageStore

"""Page-navigation metadata for the split editor's toolbar.

GET /pages/nav?path={wikisource VFS path of a Page: leaf} answers "where am
I within this index?" in one round trip: the current page number, the
index's total page count, and the previous/next sibling as ready-to-open
VFS paths. Sibling order is the same page_number sort the Pages/ listing
uses, so toolbar navigation and the tree never disagree.
"""

router = APIRouter(prefix="/pages", tags=["page-nav"], route_class=DebugLoggingRoute)


class PageNavEntry(BaseModel):
    """One Page: addressed the way the client opens files — by VFS path."""

    path: str
    title: str
    page_number: int | None = None


class PageNavInfo(BaseModel):
    current: PageNavEntry
    index_path: str
    index_title: str
    page_count: int | None = None
    position: int
    total: int
    prev: PageNavEntry | None = None
    next: PageNavEntry | None = None


@router.get("/nav", response_model=PageNavInfo)
def get_page_nav(
    path: str = Query(..., description="wikisource:// VFS path of the Page: leaf"),
    session: Session = Depends(get_session),
) -> PageNavInfo:
    store = PageStore(session)
    node = proofread_page_of(store, resolve(store, path))
    if node is None:
        raise HTTPException(status_code=404, detail=f"not a proofread page: {path}")

    index_page = node.index
    if index_page is None:
        raise HTTPException(
            status_code=404, detail=f"no Index: paginates this page: {path}"
        )
    index_title = index_page.name
    namespaces = store.site_namespaces(node.site)
    index_path = namespaces.node_path(node.site.family, node.site.code, index_title)

    siblings, metas = _ordered_siblings(store, node)
    pos = next(i for i, p in enumerate(siblings) if p.pk == node.page.pk)

    def entry(p: Entry) -> PageNavEntry:
        meta = metas.get(p.pk)
        return PageNavEntry(
            path=namespaces.node_path(
                node.site.family, node.site.code, p.name, aspect="wikitext"
            ),
            title=p.name,
            page_number=meta.page_number if meta is not None else None,
        )

    index_meta = store.index_meta(index_page.title)
    return PageNavInfo(
        current=entry(node.page),
        index_path=index_path,
        index_title=index_title,
        page_count=index_meta.page_count if index_meta is not None else None,
        position=pos + 1,
        total=len(siblings),
        prev=entry(siblings[pos - 1]) if pos > 0 else None,
        next=entry(siblings[pos + 1]) if pos + 1 < len(siblings) else None,
    )


def _ordered_siblings(
    store: PageStore, node: ProofreadPageRef
) -> tuple[list[Entry], dict[int, ProofreadPageMeta]]:
    """All Page: members of the leaf's index in Pages/-listing order —
    ascending page_number, missing numbers sorting first (as 0) — plus
    their ProofreadPageMeta rows keyed by page pk."""
    assert node.index is not None  # checked by the caller
    pages = store.proofread_pages(node.site, node.index.name)
    metas = store.proofread_page_metas_by_pks([p.pk for p in pages])

    def page_number(p: Entry) -> int:
        meta = metas.get(p.pk)
        return meta.page_number or 0 if meta is not None else 0

    return sorted(pages, key=page_number), metas
