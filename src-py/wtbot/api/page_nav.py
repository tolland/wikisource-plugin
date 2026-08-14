from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.model import Page
from wtbot.model.wikisource.proofread_page_meta import ProofreadPageMeta
from wtbot.vfs.nodes import PageLeaf, resolve
from wtbot.vfs.paths import WikiPath
from wtbot.vfs.store import PageStore

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
    node = resolve(store, path)
    if not isinstance(node, PageLeaf):
        raise HTTPException(status_code=404, detail=f"not a proofread page: {path}")

    wiki_path = WikiPath.parse(path)
    index_title = wiki_path.index_title
    index_path = "/" + "/".join(wiki_path.segments[:3])
    pages_dir = f"{index_path}/Pages"

    siblings, metas = _ordered_siblings(store, node)
    pos = next(i for i, p in enumerate(siblings) if p.pk == node.page.pk)

    def entry(p: Page) -> PageNavEntry:
        meta = metas.get(p.pk)
        return PageNavEntry(
            path=f"{pages_dir}/{p.title}",
            title=p.title,
            page_number=meta.page_number if meta is not None else None,
        )

    index_page = store.page(node.site, index_title)
    index_meta = store.index_meta(index_page) if index_page is not None else None
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
    store: PageStore, node: PageLeaf
) -> tuple[list[Page], dict[int, ProofreadPageMeta]]:
    """All Page: members of the leaf's index in Pages/-listing order —
    ascending page_number, missing numbers sorting first (as 0) — plus
    their ProofreadPageMeta rows keyed by page pk."""
    pages = store.proofread_pages(node.site, node.path.index_title)
    metas = store.proofread_page_metas_by_pks([p.pk for p in pages if p.pk is not None])

    def page_number(p: Page) -> int:
        meta = metas.get(p.pk)
        return meta.page_number or 0 if meta is not None else 0

    return sorted(pages, key=page_number), metas
