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
from wtbot.model import FileBlob, Page, Site
from wtbot.vfs.errors import BlobsNotImplemented, NotADirectory, NotAFile, NotFound
from wtbot.vfs.mediawiki import MediaWikiVfs, ts_millis
from wtbot.vfs.nodes import (
    STUB_CONTAINERS,
    FileBlobLeaf,
    FileDir,
    FileWikitext,
    IndexAssetLeaf,
    IndexDir,
    IndexWikitext,
    Missing,
    PageLeaf,
    PagesDir,
    RootDir,
    SiteDir,
    StubDir,
    resolve,
)
from wtbot.vfs.paths import WikiPath
from wtbot.vfs.store import PROOFREAD_INDEX_CONTENT_MODEL, PageStore

"""wikisource:// overlay — the ProofreadPage-aware VFS service.

This layer owns only the synthetic tree: it resolves each path to a typed
node (`wtbot.vfs.nodes`), assembles the Index/Pages/File containers, and
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


def _blob_node(path: str, blob: FileBlob | None) -> Node:
    return Node(
        path=path,
        name="blob",
        kind=NodeKind.file,
        length=blob.size if blob else None,
        writable=False,
        stable_id=None,
        revid=None,
        content_model=None,
        timestamp=None,
    )


def _index_to_file_title(index_title: str) -> str:
    _, _, rest = index_title.partition(":")
    return f"File:{rest}"


def proofread_page_scaffold() -> str:
    """Conventional skeleton for a not-yet-created proofread page, matching
    what ProofreadPage's own editor prepopulates: quality "not proofread",
    empty header/body/footer sections. Served as the *opening* body of a
    placeholder (never persisted) so the first save is well-formed."""
    return (
        '<noinclude><pagequality level="1" user="" /></noinclude>'
        "\n\n"
        "<noinclude></noinclude>"
    )


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
                    name=index.title,
                    kind=NodeKind.directory,
                    stable_id=index.pageid,
                    revid=index.revid,
                    timestamp=ts_millis(
                        index.local_modified_at or index.remote_timestamp
                    ),
                    content_model=index.content_model,
                )
            case IndexWikitext(path, _, index):
                return self.mw.stat_page(path.raw, index, name="wikitext")
            case PagesDir(path):
                return Stat(
                    path=path.raw, exists=True, name="Pages", kind=NodeKind.directory
                )
            case PageLeaf(path, _, page):
                return self.mw.stat_page(path.raw, page, name=page.title)
            case StubDir(path, name):
                return Stat(
                    path=path.raw, exists=True, name=name, kind=NodeKind.directory
                )
            case FileDir(path, _, file_page):
                return Stat(
                    path=path.raw,
                    exists=True,
                    name=file_page.title,
                    kind=NodeKind.directory,
                    stable_id=file_page.pageid,
                )
            case FileWikitext(path, _, file_page):
                return self.mw.stat_page(path.raw, file_page, name="wikitext")
            case FileBlobLeaf(path, _, file_page):
                blob = self.store.blob(file_page)
                return Stat(
                    path=path.raw,
                    exists=True,
                    name="blob",
                    kind=NodeKind.file,
                    length=blob.size if blob else None,
                )
            case IndexAssetLeaf(path, _, page, name):
                return self.mw.stat_page(path.raw, page, name=name)

    def stat_bulk(self, paths: list[str]) -> list[Stat]:
        """Batched stat() for refresh() sweeps over many cached paths at once.

        Page-under-Pages/ paths (the dominant case at real-library scale — one
        query per site+index_title rather than one per page) are batched via
        `Page.title.in_(...)`; every other path shape falls back to `stat`,
        since sites/indexes/file-dirs are comparatively few per session.
        """
        results: dict[int, Stat] = {}
        page_groups: dict[tuple[str, str, str], list[tuple[int, str, str]]] = {}

        for i, raw in enumerate(paths):
            parts = WikiPath.parse(raw).segments
            if len(parts) >= 5 and parts[3] == "Pages":
                family, code, index_title = parts[0], parts[1], parts[2]
                page_title = "/".join(parts[4:])
                page_groups.setdefault((family, code, index_title), []).append(
                    (i, raw, page_title)
                )
            else:
                results[i] = self.stat(raw)

        for (family, code, index_title), entries in page_groups.items():
            site = self.store.site(family, code)
            index_exists = (
                site is not None and self.store.page(site, index_title) is not None
            )
            if not index_exists:
                for i, raw, _ in entries:
                    results[i] = Stat(path=raw, exists=False)
                continue
            titles = [page_title for _, _, page_title in entries]
            pages = self.store.proofread_pages_by_titles(site, titles, index_title)
            pages_by_title = {p.title: p for p in pages}
            page_pks = [p.pk for p in pages if p.pk is not None]
            uncommitted = self.store.latest_uncommitted_bodies(page_pks)
            metas = self.store.page_metas_by_pks(page_pks)
            for i, raw, page_title in entries:
                page = pages_by_title.get(page_title)
                if page is None:
                    results[i] = Stat(path=raw, exists=False)
                    continue
                body = uncommitted.get(page.pk, page.text or "")
                results[i] = self.mw.stat_page(
                    raw,
                    page,
                    name=page.title,
                    body=body,
                    meta=metas.get(page.pk),
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
            case StubDir(path):
                return ListChildrenResponse(parent_path=path.normalized, children=[])
            case FileDir(path, _, file_page):
                return self._file_dir_children(path, file_page)
            case node:
                raise NotADirectory(f"not a directory: {node.path.raw}")

    def _site_children(self, path: WikiPath, site: Site) -> ListChildrenResponse:
        return ListChildrenResponse(
            parent_path=path.normalized,
            children=[
                _dir_node(f"{path.normalized}/{p.title}", p.title, stable_id=p.pageid)
                for p in self.store.indexes(site)
            ],
        )

    def _index_children(
        self, path: WikiPath, site: Site, index: Page
    ) -> ListChildrenResponse:
        parent = path.normalized
        children: list[Node] = [
            self.mw.page_node(f"{parent}/wikitext", index, name="wikitext"),
            _dir_node(f"{parent}/Pages", "Pages"),
        ]

        file_title = _index_to_file_title(index.title)
        file_page = self.store.page(site, file_title)
        if file_page is not None:
            children.append(
                _dir_node(
                    f"{parent}/{file_title}", file_title, stable_id=file_page.pageid
                )
            )

        for asset in self._index_assets(site, index):
            name = asset.title.removeprefix(f"{index.title}/")
            children.append(self.mw.page_node(f"{parent}/{name}", asset, name=name))

        children.extend(_dir_node(f"{parent}/{stub}", stub) for stub in STUB_CONTAINERS)
        return ListChildrenResponse(parent_path=parent, children=children)

    def _index_assets(self, site: Site, index: Page) -> list[Page]:
        """Non-index-content pages belonging to the index dir: title-wise
        subpages (per the mediawiki layer's namespace subpage rule) plus
        pages tied to it via their index_title link, deduplicated."""
        assets = {
            p.pk: p
            for p in self.mw.subpages(site, index.title)
            if p.content_model != PROOFREAD_INDEX_CONTENT_MODEL
        }
        for p in self.store.index_linked_assets(site, index.title):
            assets.setdefault(p.pk, p)
        return sorted(assets.values(), key=lambda p: p.title)

    def _pages_children(
        self, path: WikiPath, site: Site, index: Page
    ) -> ListChildrenResponse:
        parent = path.normalized
        pages = self.store.proofread_pages(site, index.title)
        metas = self.store.page_metas_by_pks([p.pk for p in pages if p.pk is not None])

        def page_number(p: Page) -> int:
            meta = metas.get(p.pk)
            return meta.page_number or 0 if meta is not None else 0

        return ListChildrenResponse(
            parent_path=parent,
            children=[
                self.mw.page_node(f"{parent}/{p.title}", p, meta=metas.get(p.pk))
                for p in sorted(pages, key=page_number)
            ],
        )

    def _file_dir_children(
        self, path: WikiPath, file_page: Page
    ) -> ListChildrenResponse:
        parent = path.normalized
        return ListChildrenResponse(
            parent_path=parent,
            children=[
                self.mw.page_node(f"{parent}/wikitext", file_page, name="wikitext"),
                _blob_node(f"{parent}/blob", self.store.blob(file_page)),
            ],
        )

    # -- read / write ------------------------------------------------------------

    def read(self, raw_path: str) -> ReadContentResponse:
        match resolve(self.store, raw_path):
            case PageLeaf(path, _, page) if page.revid is None:
                # Placeholder stub: open with the content-model scaffold so a
                # fresh transcription starts well-formed (local edits, once
                # journalled, take precedence via effective_body).
                return self.mw.read_page(
                    path.raw, page, default_body=proofread_page_scaffold()
                )
            case (
                PageLeaf(path, _, page)
                | IndexWikitext(path, _, page)
                | FileWikitext(path, _, page)
                | IndexAssetLeaf(path, _, page, _)
            ):
                return self.mw.read_page(path.raw, page)
            case FileBlobLeaf():
                raise BlobsNotImplemented("blob streaming not yet implemented")
            case Missing(path):
                raise NotFound(f"page not found: {path.raw}")
            case _:
                raise NotAFile("path does not refer to a file")

    def write(self, req: WriteContentRequest) -> WriteResult:
        match resolve(self.store, req.path):
            case (
                PageLeaf(_, _, page)
                | IndexWikitext(_, _, page)
                | FileWikitext(_, _, page)
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
