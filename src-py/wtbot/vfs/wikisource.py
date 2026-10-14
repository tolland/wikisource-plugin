from sqlmodel import Session

from wtbot.api.schemas import (
    ListChildrenResponse,
    Node,
    NodeKind,
    ReadContentResponse,
    Stat,
    WriteContentRequest,
    WriteResult,
    WriteStatus,
)
from wtbot.model import Site
from wtbot.vfs.errors import NotADirectory, NotAFile, NotFound
from wtbot.vfs.mediawiki import MediaWikiVfs, ts_millis
from wtbot.vfs.nodes import (
    IndexAssetLeaf,
    IndexDir,
    IndexWikitext,
    Missing,
    PageLeaf,
    PagesDir,
    RootDir,
    SiteDir,
    resolve,
)
from wtbot.vfs.paths import WikiPath, title_path
from wtbot.vfs.store import (
    PROOFREAD_INDEX_CONTENT_MODEL,
    Entry,
    PageStore,
    proofread_page_scaffold,
)

"""wikisource:// overlay — the ProofreadPage-aware VFS service.

This layer owns only the synthetic tree: it resolves each path to a typed
node (`wtbot.vfs.nodes`), assembles the Index/Pages containers, and
delegates everything title-shaped downward — per-page content operations to
the mediawiki layer, queries to the PageStore. Domain errors are raised as
`wtbot.vfs.errors` types; the HTTP router maps them to status codes.

Reuses the pydantic response models from `wtbot.api.schemas` directly —
they are the wire contract either way, and a parallel DTO layer would only
add mapping noise.
"""


def _dir_node(path: str, name: str, stable_id: int | None = None) -> Node:
    return Node(
        path=path,
        name=name,
        kind=NodeKind.directory,
        stable_id=stable_id,
        writable=False,
    )


__all__ = ["WikisourceVfs", "proofread_page_scaffold"]


class WikisourceVfs:
    """ProofreadPage overlay over the local page cache.

    Pure cache reads/writes — never triggers a wiki fetch (see DESIGN.md's
    "git, not Samba" model). One instance per request/session.
    """

    def __init__(self, session: Session) -> None:
        self.store = PageStore(session)
        self.mw = MediaWikiVfs(self.store)

    # -- stat ----------------------------------------------------------------

    def stat(self, raw_path: str) -> Stat:
        match resolve(self.store, raw_path):
            case Missing(path):
                return Stat(path=path.raw, exists=False)
            case RootDir(path):
                return Stat(
                    path=path.raw, exists=True, name="/", kind=NodeKind.directory
                )
            case SiteDir(path, site):
                return Stat(
                    path=path.raw,
                    exists=True,
                    name=f"{site.family}/{site.code}",
                    kind=NodeKind.directory,
                )
            case IndexDir(path, _, index):
                return Stat(
                    path=path.raw,
                    exists=True,
                    name=index.name,
                    kind=NodeKind.directory,
                    stable_id=index.pageid,
                    revid=index.revid,
                    timestamp=ts_millis(index.timestamp),
                    content_model=index.content_model,
                )
            case IndexWikitext(path, _, index):
                return self.mw.stat_page(path.raw, index, name="wikitext")
            case PagesDir(path):
                return Stat(
                    path=path.raw, exists=True, name="Pages", kind=NodeKind.directory
                )
            case PageLeaf(path, _, page):
                return self.mw.stat_page(path.raw, page, name=page.name)
            case IndexAssetLeaf(path, _, page, name):
                return self.mw.stat_page(path.raw, page, name=name)

    def stat_bulk(self, paths: list[str]) -> list[Stat]:
        """Batched stat() for refresh() sweeps over many cached paths at once.

        Page: titles (the dominant case at real-library scale) are batched --
        one query per site rather than one per page -- via
        `Title.title.in_(...)`; every other path shape, and any title that is
        not a known Page:, falls back to `stat`, since sites/indexes/assets
        are comparatively few per session.
        """
        results: dict[int, Stat] = {}
        by_site: dict[tuple[str, str], list[tuple[int, str, str]]] = {}

        for i, raw in enumerate(paths):
            parts = WikiPath.parse(raw).segments
            if len(parts) >= 3:
                by_site.setdefault((parts[0], parts[1]), []).append(
                    (i, raw, "/".join(parts[2:]))
                )
            else:
                results[i] = self.stat(raw)

        for (family, code), entries in by_site.items():
            site = self.store.site(family, code)
            if site is None:
                for i, raw, _ in entries:
                    results[i] = Stat(path=raw, exists=False)
                continue
            titles = [title for _, _, title in entries]
            pages = self.store.proofread_pages_by_titles(site, titles)
            pages_by_title = {p.name: p for p in pages}
            page_pks = [p.pk for p in pages]
            uncommitted = self.store.latest_uncommitted_bodies(page_pks)
            metas = self.store.proofread_page_metas_by_pks(page_pks)
            # For every page, not just those without local edits: a page can
            # have an uncommitted save (which supplies the body) *and* an
            # earlier push whose refetch is still queued (which supplies the
            # revid), and those are answered independently.
            pushed = self.store.latest_successful_commits(page_pks)
            for i, raw, title in entries:
                page = pages_by_title.get(title)
                if page is None:
                    results[i] = self.stat(raw)
                    continue
                # Same rule as the single-page path, over rows already loaded
                # in bulk -- restating it here is how the two drifted apart.
                meta = metas.get(page.pk)
                state = self.store.effective_state_from(
                    page,
                    uncommitted_body=uncommitted.get(page.pk),
                    commit=pushed.get(page.pk),
                    proposed=self.store.proposed_body(page, meta),
                )
                results[i] = self.mw.stat_page(
                    raw, page, name=page.name, state=state, meta=meta
                )

        return [results[i] for i in range(len(paths))]

    # -- list_children ---------------------------------------------------------

    def list_children(self, raw_path: str) -> ListChildrenResponse:
        match resolve(self.store, raw_path):
            case Missing(path):
                raise NotFound(f"path not found: {path.raw}")
            case RootDir(path):
                return ListChildrenResponse(
                    parent_path=path.normalized,
                    children=[
                        _dir_node(f"/{s.family}/{s.code}", f"{s.family}/{s.code}")
                        for s in self.store.sites()
                    ],
                )
            case SiteDir(path, site):
                return self._site_children(path, site)
            case IndexDir(path, site, index):
                return self._index_children(path, site, index)
            case PagesDir(path, site, index):
                return self._pages_children(path, site, index)
            case node:
                raise NotADirectory(f"not a directory: {node.path.raw}")

    def _site_children(self, path: WikiPath, site: Site) -> ListChildrenResponse:
        return ListChildrenResponse(
            parent_path=path.normalized,
            children=[
                _dir_node(f"{path.normalized}/{p.name}", p.name, stable_id=p.pageid)
                for p in self.store.indexes(site)
            ],
        )

    def _index_children(
        self, path: WikiPath, site: Site, index: Entry
    ) -> ListChildrenResponse:
        parent = path.normalized
        children: list[Node] = [
            self.mw.page_node(f"{parent}/wikitext", index, name="wikitext"),
            _dir_node(f"{parent}/Pages", "Pages"),
        ]

        for asset in self._index_assets(site, index):
            name = asset.name.removeprefix(f"{index.name}/")
            children.append(self.mw.page_node(f"{parent}/{name}", asset, name=name))
        return ListChildrenResponse(parent_path=parent, children=children)

    def _index_assets(self, site: Site, index: Entry) -> list[Entry]:
        """Non-index-content title-wise subpages of the Index page."""
        assets = {
            p.pk: p
            for p in self.mw.subpages(site, index.name)
            if p.content_model != PROOFREAD_INDEX_CONTENT_MODEL
        }
        return sorted(assets.values(), key=lambda p: p.name)

    def _pages_children(
        self, path: WikiPath, site: Site, index: Entry
    ) -> ListChildrenResponse:
        parent = path.normalized
        pages = self.store.proofread_pages(site, index.name)
        metas = self.store.proofread_page_metas_by_pks([p.pk for p in pages])

        def page_number(p: Entry) -> int:
            meta = metas.get(p.pk)
            return meta.page_number or 0 if meta is not None else 0

        children: list[Node] = [
            self.mw.page_node(
                title_path(site.family, site.code, p.name), p, meta=metas.get(p.pk)
            )
            for p in sorted(pages, key=page_number)
        ]
        return ListChildrenResponse(parent_path=parent, children=children)

    # -- read / write ------------------------------------------------------------

    def read(self, raw_path: str) -> ReadContentResponse:
        match resolve(self.store, raw_path):
            case (
                PageLeaf(path, _, page)
                | IndexWikitext(path, _, page)
                | IndexAssetLeaf(path, _, page, _)
            ):
                return self.mw.read_page(path.raw, page)
            case Missing(path):
                raise NotFound(f"page not found: {path.raw}")
            case _:
                raise NotAFile("path does not refer to a file")

    def write(self, req: WriteContentRequest) -> WriteResult:
        match resolve(self.store, req.path):
            case (
                PageLeaf(_, _, page)
                | IndexWikitext(_, _, page)
                | IndexAssetLeaf(_, _, page, _)
            ):
                return self.mw.write_page(req, page)
            case Missing(path):
                return WriteResult(
                    path=req.path,
                    status=WriteStatus.error,
                    message=f"page not found: {path.raw}",
                )
            case _:
                return WriteResult(
                    path=req.path,
                    status=WriteStatus.error,
                    message="path is not a writable file",
                )
