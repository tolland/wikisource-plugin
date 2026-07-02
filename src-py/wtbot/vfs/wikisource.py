import base64
from datetime import datetime, timezone

from sqlmodel import Session, select

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
from wtbot.model import EditJournal, FileBlob, Page, Site
from wtbot.model.namespace import NsRole
from wtbot.vfs.errors import BlobsNotImplemented, NotADirectory, NotAFile, NotFound
from wtbot.vfs.nodes import (
    PROOFREAD_INDEX_CONTENT_MODEL,
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

"""wikisource:// overlay — the ProofreadPage-aware VFS service.

Every operation resolves its path to a typed node (`wtbot.vfs.nodes`) and
then match/cases on the node kind, so path classification lives in exactly
one place. Domain errors are raised as `wtbot.vfs.errors` types; the HTTP
router maps them to status codes. Reuses the pydantic response models from
`wtbot.api.schemas` directly — they are the wire contract either way, and a
parallel DTO layer would only add mapping noise.

Planned step 3 of the refactor pulls the raw SQL below into a PageStore and
a title-addressed mediawiki:// layer beneath this one (see the discussion in
the VFS refactor outline); for now this module owns both.
"""


def _ts(dt: datetime | None) -> str | None:
    """Milliseconds-since-epoch string for VirtualFile.getTimeStamp()."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return str(int(dt.timestamp() * 1000))


def _b64(body: str) -> str:
    return base64.b64encode(body.encode()).decode()


def _index_to_file_title(index_title: str) -> str:
    _, _, rest = index_title.partition(":")
    return f"File:{rest}"


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


class WikisourceVfs:
    """ProofreadPage overlay over the local page cache.

    Pure cache reads/writes — never triggers a wiki fetch (see DESIGN.md's
    "git, not Samba" model). One instance per request/session.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # -- body discipline ----------------------------------------------------

    def _effective_body(self, page: Page) -> str:
        """The body read()/stat() should report for [page].

        Page.text is the cached *remote* body — written only by the fetch
        worker on refresh from the wiki. Local IDE saves must never touch it,
        or it stops meaning "what's on the wiki" and a refresh silently loses
        the diff base. Instead, a save appends an EditJournal row; this reads
        the most recent uncommitted one back, falling back to Page.text when
        there's nothing uncommitted (never edited locally, or already pushed
        and marked committed).
        """
        latest = self.session.exec(
            select(EditJournal)
            .where(EditJournal.page_pk == page.pk)
            .where(EditJournal.committed == False)  # noqa: E712
            .order_by(EditJournal.saved_at.desc())
            .limit(1)
        ).first()
        if latest is not None:
            return latest.body
        return page.text or ""

    def _latest_uncommitted_bodies(self, page_pks: list[int]) -> dict[int, str]:
        """Batched form of [_effective_body]'s EditJournal lookup, for call
        sites (stat_bulk) that already batch their Page query and shouldn't
        regress to one EditJournal query per page."""
        if not page_pks:
            return {}
        rows = self.session.exec(
            select(EditJournal)
            .where(EditJournal.page_pk.in_(page_pks))
            .where(EditJournal.committed == False)  # noqa: E712
            .order_by(EditJournal.saved_at)
        ).all()
        # Rows are ascending by saved_at, so the last write per page_pk wins.
        return {row.page_pk: row.body for row in rows}

    # -- stat ----------------------------------------------------------------

    def stat(self, raw_path: str) -> Stat:
        match resolve(self.session, raw_path):
            case Missing(path):
                return Stat(path=path.raw, exists=False)
            case RootDir(path):
                return Stat(path=path.raw, exists=True, name="/", kind=NodeKind.directory)
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
                    timestamp=_ts(index.local_modified_at or index.remote_timestamp),
                    content_model=index.content_model,
                )
            case IndexWikitext(path, _, index):
                return self._file_stat(path.raw, index, name="wikitext")
            case PagesDir(path):
                return Stat(path=path.raw, exists=True, name="Pages", kind=NodeKind.directory)
            case PageLeaf(path, _, page):
                return self._file_stat(path.raw, page, name=page.title)
            case StubDir(path, name):
                return Stat(path=path.raw, exists=True, name=name, kind=NodeKind.directory)
            case FileDir(path, _, file_page):
                return Stat(
                    path=path.raw,
                    exists=True,
                    name=file_page.title,
                    kind=NodeKind.directory,
                    stable_id=file_page.pageid,
                )
            case FileWikitext(path, _, file_page):
                return self._file_stat(path.raw, file_page, name="wikitext")
            case FileBlobLeaf(path, _, file_page):
                blob = self._blob_for(file_page)
                return Stat(
                    path=path.raw,
                    exists=True,
                    name="blob",
                    kind=NodeKind.file,
                    length=blob.size if blob else None,
                )
            case IndexAssetLeaf(path, _, page, name):
                return self._file_stat(path.raw, page, name=name)

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
            site = self.session.exec(
                select(Site).where(Site.family == family, Site.code == code)
            ).first()
            index_exists = site is not None and (
                self.session.exec(
                    select(Page.pk).where(
                        Page.site_pk == site.pk, Page.title == index_title
                    )
                ).first()
                is not None
            )
            if not index_exists:
                for i, raw, _ in entries:
                    results[i] = Stat(path=raw, exists=False)
                continue
            titles = [page_title for _, _, page_title in entries]
            pages = self.session.exec(
                select(Page).where(
                    Page.site_pk == site.pk,
                    Page.title.in_(titles),
                    # Same membership filters as resolve()'s PageLeaf branch —
                    # bulk and individual stat must never disagree.
                    Page.namespace_role == NsRole.page,
                    Page.index_title == index_title,
                )
            ).all()
            pages_by_title = {p.title: p for p in pages}
            uncommitted = self._latest_uncommitted_bodies(
                [p.pk for p in pages if p.pk is not None]
            )
            for i, raw, page_title in entries:
                page = pages_by_title.get(page_title)
                if page is None:
                    results[i] = Stat(path=raw, exists=False)
                    continue
                body = uncommitted.get(page.pk, page.text or "")
                results[i] = self._file_stat(raw, page, name=page.title, body=body)

        return [results[i] for i in range(len(paths))]

    def _file_stat(
        self, raw_path: str, page: Page, name: str, body: str | None = None
    ) -> Stat:
        if body is None:
            body = self._effective_body(page)
        return Stat(
            path=raw_path,
            exists=True,
            name=name,
            kind=NodeKind.file,
            stable_id=page.pageid,
            revid=page.revid,
            timestamp=_ts(page.local_modified_at or page.remote_timestamp),
            length=len(body.encode()),
            content_model=page.content_model,
        )

    # -- list_children ---------------------------------------------------------

    def list_children(self, raw_path: str) -> ListChildrenResponse:
        match resolve(self.session, raw_path):
            case Missing(path):
                raise NotFound(f"path not found: {path.raw}")
            case RootDir(path):
                sites = self.session.exec(select(Site)).all()
                return ListChildrenResponse(
                    parent_path=path.normalized,
                    children=[
                        _dir_node(f"/{s.family}/{s.code}", f"{s.family}/{s.code}")
                        for s in sites
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
        indexes = self.session.exec(
            select(Page).where(
                Page.site_pk == site.pk,
                Page.content_model == PROOFREAD_INDEX_CONTENT_MODEL,
            )
        ).all()
        return ListChildrenResponse(
            parent_path=path.normalized,
            children=[
                _dir_node(f"{path.normalized}/{p.title}", p.title, stable_id=p.pageid)
                for p in indexes
            ],
        )

    def _index_children(
        self, path: WikiPath, site: Site, index: Page
    ) -> ListChildrenResponse:
        parent = path.normalized
        children: list[Node] = [
            self._page_node(f"{parent}/wikitext", index, name="wikitext"),
            _dir_node(f"{parent}/Pages", "Pages"),
        ]

        file_title = _index_to_file_title(index.title)
        file_page = self.session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == file_title)
        ).first()
        if file_page is not None:
            children.append(
                _dir_node(f"{parent}/{file_title}", file_title, stable_id=file_page.pageid)
            )

        asset_candidates = self.session.exec(
            select(Page)
            .where(
                Page.site_pk == site.pk,
                Page.namespace_role == NsRole.index,
                Page.content_model != PROOFREAD_INDEX_CONTENT_MODEL,
            )
            .order_by(Page.title)
        ).all()
        prefix = f"{index.title}/"
        for asset in asset_candidates:
            if asset.index_title != index.title and not asset.title.startswith(prefix):
                continue
            name = asset.title.removeprefix(prefix)
            children.append(self._page_node(f"{parent}/{name}", asset, name=name))

        children.extend(_dir_node(f"{parent}/{stub}", stub) for stub in STUB_CONTAINERS)
        return ListChildrenResponse(parent_path=parent, children=children)

    def _pages_children(
        self, path: WikiPath, site: Site, index: Page
    ) -> ListChildrenResponse:
        pages = self.session.exec(
            select(Page).where(
                Page.site_pk == site.pk,
                Page.namespace_role == NsRole.page,
                Page.index_title == index.title,
            )
        ).all()
        parent = path.normalized
        return ListChildrenResponse(
            parent_path=parent,
            children=[
                self._page_node(f"{parent}/{p.title}", p)
                for p in sorted(pages, key=lambda p: p.page_number or 0)
            ],
        )

    def _file_dir_children(self, path: WikiPath, file_page: Page) -> ListChildrenResponse:
        parent = path.normalized
        return ListChildrenResponse(
            parent_path=parent,
            children=[
                self._page_node(f"{parent}/wikitext", file_page, name="wikitext"),
                _blob_node(f"{parent}/blob", self._blob_for(file_page)),
            ],
        )

    def _page_node(self, path: str, page: Page, name: str | None = None) -> Node:
        body = self._effective_body(page)
        return Node(
            path=path,
            name=name if name is not None else page.title,
            kind=NodeKind.file,
            stable_id=page.pageid,
            revid=page.revid,
            timestamp=_ts(page.local_modified_at or page.remote_timestamp),
            length=len(body.encode()),
            writable=True,
            content_model=page.content_model,
        )

    def _blob_for(self, file_page: Page) -> FileBlob | None:
        return self.session.exec(
            select(FileBlob).where(FileBlob.page_pk == file_page.pk)
        ).first()

    # -- read / write ------------------------------------------------------------

    def read(self, raw_path: str) -> ReadContentResponse:
        match resolve(self.session, raw_path):
            case (
                PageLeaf(path, _, page)
                | IndexWikitext(path, _, page)
                | FileWikitext(path, _, page)
                | IndexAssetLeaf(path, _, page, _)
            ):
                return ReadContentResponse(
                    path=path.raw,
                    revid=page.revid,
                    content_base64=_b64(self._effective_body(page)),
                )
            case FileBlobLeaf():
                raise BlobsNotImplemented("blob streaming not yet implemented")
            case Missing(path):
                raise NotFound(f"page not found: {path.raw}")
            case _:
                raise NotAFile("path does not refer to a file")

    def write(self, req: WriteContentRequest) -> WriteResult:
        """Local save only — appends an EditJournal row. Does not touch the
        wiki (that happens later when the commit worker drains uncommitted
        journal rows via pywikibot) and does NOT touch Page.text: that field
        is the cached *remote* body, written only by the fetch worker on
        refresh, and is the diff base for conflict detection — overwriting it
        here on every keystroke-triggered save would silently destroy that
        base. read()/stat() serve the effective (edited-or-remote) body via
        _effective_body(), which reads this journal back."""
        match resolve(self.session, req.path):
            case (
                PageLeaf(_, _, page)
                | IndexWikitext(_, _, page)
                | FileWikitext(_, _, page)
                | IndexAssetLeaf(_, _, page, _)
            ):
                return self._write_page(req, page)
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

    def _write_page(self, req: WriteContentRequest, page: Page) -> WriteResult:
        if (
            req.base_revid is not None
            and page.revid is not None
            and req.base_revid != page.revid
        ):
            return WriteResult(
                path=req.path,
                status=WriteStatus.conflict,
                new_revid=page.revid,
                message=f"remote revid is {page.revid}, edit was based on {req.base_revid}",
            )

        journal = EditJournal(
            page_pk=page.pk,
            base_revid=req.base_revid if req.base_revid is not None else page.revid,
            body=base64.b64decode(req.content_base64).decode(),
            comment=req.comment,
        )
        self.session.add(journal)

        page.dirty = True
        page.local_modified_at = datetime.now(timezone.utc)
        self.session.add(page)

        self.session.commit()

        # Local save succeeds without a new remote revid — the page is still
        # on page.revid until the commit worker pushes it.
        return WriteResult(path=req.path, status=WriteStatus.ok, new_revid=page.revid)
