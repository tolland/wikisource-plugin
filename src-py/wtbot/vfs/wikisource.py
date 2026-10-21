import base64
import re

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
from wtbot.model.wikisource.proofread_page_meta import ProofreadPageMeta
from wtbot.vfs.aspects import PROPS_CONTENT_MODEL, props_body
from wtbot.vfs.errors import NotADirectory, NotAFile, NotFound
from wtbot.vfs.mediawiki import MediaWikiVfs, ts_millis
from wtbot.vfs.namespaces import NsView, SiteNamespaces
from wtbot.vfs.nodes import (
    ASPECT_PAGES,
    ASPECT_PROPS,
    ASPECT_WIKITEXT,
    AspectLeaf,
    Missing,
    NamespaceDir,
    PagesDir,
    RootDir,
    SiteDir,
    TitleNode,
    aspect_names,
    resolve,
)
from wtbot.vfs.paths import ASPECT_PREFIX, WikiPath, aspect_path
from wtbot.vfs.store import (
    PROOFREAD_INDEX_CONTENT_MODEL,
    Entry,
    PageStore,
    proofread_page_scaffold,
)

"""wikisource:// overlay — the ProofreadPage-aware VFS service.

This layer owns only the synthetic tree: it resolves each path to a typed
node (`wtbot.vfs.nodes`), assembles the namespace/title containers and the
aspect files, and delegates everything title-shaped downward — per-page
content operations to the mediawiki layer, queries to the PageStore. Domain
errors are raised as `wtbot.vfs.errors` types; the HTTP router maps them to
status codes.

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
        has_children=True,
    )


def _natural(text: str) -> list[int | str]:
    """Sort key putting `Foo/2` before `Foo/10`."""
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", text)]


def _last_segment(rest: str) -> str:
    return rest.rsplit("/", 1)[-1]


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
                    has_children=True,
                )
            case NamespaceDir(path, _, _, ns):
                return Stat(
                    path=path.raw,
                    exists=True,
                    name=ns.name,
                    kind=NodeKind.directory,
                    has_children=True,
                )
            case TitleNode() as node:
                return self._title_stat(node, raw_path)
            case AspectLeaf(path, node, aspect):
                return self._aspect_stat(path.raw, node, aspect)
            case PagesDir(path):
                return Stat(
                    path=path.raw,
                    exists=True,
                    name=f"{ASPECT_PREFIX}{ASPECT_PAGES}",
                    kind=NodeKind.directory,
                    has_children=True,
                )

    def _title_stat(self, node: TitleNode, raw_path: str) -> Stat:
        name = _last_segment(node.rest)
        has_children = self._has_children(node)
        if node.entry is None:
            return Stat(
                path=raw_path,
                exists=True,
                name=name,
                kind=NodeKind.directory,
                has_children=has_children,
            )
        return self.mw.title_stat(
            raw_path,
            name,
            node.entry,
            has_children=has_children,
            aspects=aspect_names(node.entry),
        )

    def _has_children(self, node: TitleNode) -> bool:
        if node.is_index:
            return True
        return node.ns.subpages and self.store.has_titles_under(
            node.site, f"{node.title}/"
        )

    def _aspect_stat(self, raw_path: str, node: TitleNode, aspect: str) -> Stat:
        entry = node.entry
        assert entry is not None
        name = f"{ASPECT_PREFIX}{aspect}"
        if aspect == ASPECT_PROPS:
            body = props_body(self.store, node, entry)
            return Stat(
                path=raw_path,
                exists=True,
                name=name,
                kind=NodeKind.file,
                stable_id=entry.pageid,
                revid=entry.revid,
                timestamp=ts_millis(entry.timestamp),
                length=len(body.encode()),
                content_model=PROPS_CONTENT_MODEL,
            )
        return self.mw.stat_page(raw_path, entry, name=name)

    def stat_bulk(self, paths: list[str]) -> list[Stat]:
        """Batched stat() for refresh() sweeps over many cached paths at once.

        The `@wikitext` files (the dominant case at real-library scale) are
        batched -- one query per site rather than one per page -- via
        `Title.title.in_(...)`; every other path shape, and any title that is
        not held, falls back to `stat`, since sites/containers/props are
        comparatively few per session.
        """
        results: dict[int, Stat] = {}
        by_site: dict[tuple[str, str], list[tuple[int, str]]] = {}

        for i, raw in enumerate(paths):
            path = WikiPath.parse(raw)
            if len(path.segments) >= 4 and path.aspect == ASPECT_WIKITEXT:
                by_site.setdefault((path.family, path.code), []).append((i, raw))
            else:
                results[i] = self.stat(raw)

        for (family, code), entries in by_site.items():
            site = self.store.site(family, code)
            if site is None:
                for i, raw in entries:
                    results[i] = Stat(path=raw, exists=False)
                continue
            self._stat_wikitext_batch(site, entries, results)

        return [results[i] for i in range(len(paths))]

    def _stat_wikitext_batch(
        self,
        site: Site,
        entries: list[tuple[int, str]],
        results: dict[int, Stat],
    ) -> None:
        namespaces = self.store.site_namespaces(site)
        wanted: dict[int, str] = {}
        for i, raw in entries:
            path = WikiPath.parse(raw)
            ns = namespaces.by_segment(path.namespace_segment)
            if ns is not None and path.title_rest:
                wanted[i] = ns.title(path.title_rest)

        pages = self.store.entries_by_titles(site, list(wanted.values()))
        by_title = {p.name: p for p in pages}
        page_pks = [p.pk for p in pages]
        uncommitted = self.store.latest_uncommitted_bodies(page_pks)
        metas = self.store.proofread_page_metas_by_pks(page_pks)
        # For every page, not just those without local edits: a page can
        # have an uncommitted save (which supplies the body) *and* an
        # earlier push whose refetch is still queued (which supplies the
        # revid), and those are answered independently.
        pushed = self.store.latest_successful_commits(page_pks)
        for i, raw in entries:
            page = by_title.get(wanted.get(i, ""))
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
                raw,
                page,
                name=f"{ASPECT_PREFIX}{ASPECT_WIKITEXT}",
                state=state,
                meta=meta,
            )

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
            case SiteDir(path, site, namespaces):
                return self._site_children(path, site, namespaces)
            case NamespaceDir(path, site, namespaces, ns):
                return self._namespace_children(path, site, namespaces, ns)
            case TitleNode() as node:
                return self._title_children(node)
            case PagesDir() as pages:
                return self._pages_children(pages)
            case node:
                raise NotADirectory(f"not a directory: {node.path.raw}")

    def _site_children(
        self, path: WikiPath, site: Site, namespaces: SiteNamespaces
    ) -> ListChildrenResponse:
        """The namespaces the cache has titles in."""
        present = {
            namespaces.split(f"{prefix}x")[0]
            for prefix in self.store.title_prefixes(site)
        }
        return ListChildrenResponse(
            parent_path=path.normalized,
            children=[
                _dir_node(f"{path.normalized}/{ns.name}", ns.name)
                for ns in namespaces.all()
                if ns in present and ns.listed
            ],
        )

    def _namespace_children(
        self, path: WikiPath, site: Site, namespaces: SiteNamespaces, ns: NsView
    ) -> ListChildrenResponse:
        titles = self.store.namespace_titles(site, namespaces, ns)
        return ListChildrenResponse(
            parent_path=path.normalized,
            children=self._subpage_nodes(site, namespaces, ns, titles, parent=None),
        )

    def _title_children(self, node: TitleNode) -> ListChildrenResponse:
        """A title's aspects (files), then its subpages."""
        parent = node.path.normalized
        children: list[Node] = []
        entry = node.entry
        if entry is not None:
            children.append(
                self.mw.page_node(
                    aspect_path(parent, ASPECT_WIKITEXT),
                    entry,
                    name=f"{ASPECT_PREFIX}{ASPECT_WIKITEXT}",
                )
            )
            children.append(self._props_node(parent, node, entry))
            if node.is_index:
                children.append(
                    _dir_node(
                        aspect_path(parent, ASPECT_PAGES),
                        f"{ASPECT_PREFIX}{ASPECT_PAGES}",
                    )
                )
        if node.ns.subpages:
            titles = self.store.titles_under(node.site, f"{node.title}/")
            children += self._subpage_nodes(
                node.site, node.namespaces, node.ns, titles, parent=node.rest
            )
        return ListChildrenResponse(parent_path=parent, children=children)

    def _props_node(self, parent: str, node: TitleNode, entry: Entry) -> Node:
        body = props_body(self.store, node, entry)
        return Node(
            path=aspect_path(parent, ASPECT_PROPS),
            name=f"{ASPECT_PREFIX}{ASPECT_PROPS}",
            kind=NodeKind.file,
            stable_id=entry.pageid,
            revid=entry.revid,
            timestamp=ts_millis(entry.timestamp),
            length=len(body.encode()),
            writable=False,
            content_model=PROPS_CONTENT_MODEL,
        )

    def _subpage_nodes(
        self,
        site: Site,
        namespaces: SiteNamespaces,
        ns: NsView,
        titles: list[str],
        parent: str | None,
    ) -> list[Node]:
        """The title nodes one level below [parent] (None: the namespace
        itself), from the full titles at or below it.

        In a namespace with subpages, `A/B/C` is a descendant of `A` through
        `A/B` -- which is a synthetic node when nothing holds it. Without
        subpages the slash belongs to the title, so every title is one node.
        """
        base = "" if parent is None else f"{parent}/"
        has_deeper: dict[str, bool] = {}
        for full in titles:
            rest = full[len(ns.prefix) :]
            if rest == parent or not rest.startswith(base):
                continue
            tail = rest[len(base) :]
            segment, sep, _ = tail.partition("/") if ns.subpages else (tail, "", "")
            child = f"{base}{segment}"
            has_deeper[child] = has_deeper.get(child, False) or bool(sep)

        children = sorted(has_deeper, key=_natural)
        entries = {
            e.name: e
            for e in self.store.entries_by_titles(site, [ns.title(c) for c in children])
        }
        metas = self.store.proofread_page_metas_by_pks([e.pk for e in entries.values()])
        return [
            self._title_child(
                site,
                namespaces,
                ns.title(child),
                entries.get(ns.title(child)),
                has_deeper[child],
                metas,
            )
            for child in children
        ]

    def _title_child(
        self,
        site: Site,
        namespaces: SiteNamespaces,
        full_title: str,
        entry: Entry | None,
        has_subpages: bool,
        metas: dict[int, ProofreadPageMeta],
    ) -> Node:
        path = namespaces.node_path(site.family, site.code, full_title)
        name = _last_segment(namespaces.split(full_title)[1])
        if entry is None:
            return _dir_node(path, name)
        return self.mw.title_node(
            path,
            name,
            entry,
            has_children=has_subpages
            or entry.content_model == PROOFREAD_INDEX_CONTENT_MODEL,
            aspects=aspect_names(entry),
            meta=metas.get(entry.pk),
        )

    def _pages_children(self, node: PagesDir) -> ListChildrenResponse:
        site, index = node.site, node.index
        namespaces = node.node.namespaces
        pages = self.store.proofread_pages(site, index.name)
        metas = self.store.proofread_page_metas_by_pks([p.pk for p in pages])

        def page_number(p: Entry) -> int:
            meta = metas.get(p.pk)
            return meta.page_number or 0 if meta is not None else 0

        return ListChildrenResponse(
            parent_path=node.path.normalized,
            children=[
                self._title_child(site, namespaces, p.name, p, False, metas)
                for p in sorted(pages, key=page_number)
            ],
        )

    # -- read / write ------------------------------------------------------------

    def read(self, raw_path: str) -> ReadContentResponse:
        match resolve(self.store, raw_path):
            case AspectLeaf(path, node, aspect) if aspect == ASPECT_PROPS:
                assert node.entry is not None
                body = props_body(self.store, node, node.entry)
                return ReadContentResponse(
                    path=path.raw,
                    revid=node.entry.revid,
                    content_base64=base64.b64encode(body.encode()).decode(),
                )
            case AspectLeaf(path, node, _):
                assert node.entry is not None
                return self.mw.read_page(path.raw, node.entry)
            case Missing(path):
                raise NotFound(f"page not found: {path.raw}")
            case _:
                raise NotAFile("path does not refer to a file")

    def write(self, req: WriteContentRequest) -> WriteResult:
        match resolve(self.store, req.path):
            case AspectLeaf(_, node, aspect) if aspect == ASPECT_WIKITEXT:
                assert node.entry is not None
                return self.mw.write_page(req, node.entry)
            case AspectLeaf(aspect=aspect):
                return WriteResult(
                    path=req.path,
                    status=WriteStatus.error,
                    message=f"the {aspect} aspect is read-only",
                )
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
