from __future__ import annotations

from dataclasses import dataclass

from wtbot.model import Site
from wtbot.vfs.namespaces import NsView, SiteNamespaces
from wtbot.vfs.paths import WikiPath
from wtbot.vfs.store import (
    PROOFREAD_INDEX_CONTENT_MODEL,
    PROOFREAD_PAGE_CONTENT_MODEL,
    Entry,
    PageStore,
)

"""Typed resolution of wikisource:// paths.

`resolve()` is the single place that classifies a path against the tree:

    /                                          RootDir
    /{family}/{code}                           SiteDir
    /{family}/{code}/{namespace}               NamespaceDir  (`(Main)` for main)
    /{family}/{code}/{ns}/{title segments}     TitleNode     (a title, as a container)
    .../{title}/@wikitext                      AspectLeaf    (its content)
    .../{title}/@props                         AspectLeaf    (its properties)
    .../{Index title}/@pages                   PagesDir      (the Page: titles it paginates)

A title is a *node*: it can be a page, a container of subpages, or both, and
offers any number of aspects. Aspects are the files; nodes are the
directories. That keeps one path stable for each thing you can open, however
many subpages the title later gains.

A title is a node when the wiki holds it, or when titles exist below it
(`Book:A/B` makes a synthetic `Book:A` with no entry of its own). Whether a
slash in a title is a subpage separator is the namespace's `subpages` flag.

Every VFS operation (stat / list / read / write) resolves first and then
match/cases on the node type, so the tree shape is defined exactly once.
Nodes carry the ORM rows the resolver already fetched; operations must not
re-query what the resolver proved to exist.
"""

ASPECT_WIKITEXT = "wikitext"
ASPECT_PROPS = "props"
ASPECT_PAGES = "pages"

AspectName = str


@dataclass(frozen=True, slots=True)
class RootDir:
    path: WikiPath


@dataclass(frozen=True, slots=True)
class SiteDir:
    path: WikiPath
    site: Site
    namespaces: SiteNamespaces


@dataclass(frozen=True, slots=True)
class NamespaceDir:
    path: WikiPath
    site: Site
    namespaces: SiteNamespaces
    ns: NsView


@dataclass(frozen=True, slots=True)
class TitleNode:
    """A title as a container. `entry` is None for a synthetic node: no page
    or title of its own, only titles below it."""

    path: WikiPath
    site: Site
    namespaces: SiteNamespaces
    ns: NsView
    rest: str
    """The title below the namespace prefix."""
    entry: Entry | None

    @property
    def title(self) -> str:
        return self.ns.title(self.rest)

    @property
    def is_index(self) -> bool:
        return (
            self.entry is not None
            and self.entry.content_model == PROOFREAD_INDEX_CONTENT_MODEL
        )

    @property
    def node_path(self) -> str:
        return self.path.node_path


@dataclass(frozen=True, slots=True)
class AspectLeaf:
    """One aspect of a title that has an entry: a file."""

    path: WikiPath
    node: TitleNode
    aspect: AspectName

    @property
    def site(self) -> Site:
        return self.node.site

    @property
    def entry(self) -> Entry:
        assert self.node.entry is not None
        return self.node.entry


@dataclass(frozen=True, slots=True)
class PagesDir:
    """The `@pages` aspect of an Index: the Page: titles it paginates. Has no
    underlying wiki page, hence no stable_id."""

    path: WikiPath
    node: TitleNode

    @property
    def site(self) -> Site:
        return self.node.site

    @property
    def index(self) -> Entry:
        assert self.node.entry is not None
        return self.node.entry


@dataclass(frozen=True, slots=True)
class Missing:
    path: WikiPath


type WsNode = (
    RootDir | SiteDir | NamespaceDir | TitleNode | AspectLeaf | PagesDir | Missing
)


def aspect_names(entry: Entry | None) -> list[AspectName]:
    """The aspects a title offers, default first. A synthetic node has no
    entry, so it offers none."""
    if entry is None:
        return []
    names = [ASPECT_WIKITEXT, ASPECT_PROPS]
    if entry.content_model == PROOFREAD_INDEX_CONTENT_MODEL:
        names.append(ASPECT_PAGES)
    return names


def entry_behind(node: WsNode) -> Entry | None:
    """The cached title a node names or belongs to, for callers that only
    care which page a path points at -- whether the path names the title or
    one of its aspects. Containers with no page of their own (a synthetic
    node, `@pages`) have none."""
    match node:
        case TitleNode(entry=entry):
            return entry
        case AspectLeaf():
            return node.entry
        case _:
            return None


@dataclass(frozen=True, slots=True)
class ProofreadPageRef:
    """A proofread `Page:` title and the Index: that paginates it, if its
    metadata names one."""

    site: Site
    page: Entry
    index: Entry | None


def proofread_page_of(store: PageStore, node: WsNode) -> ProofreadPageRef | None:
    """The proofread page a path names -- as the title itself or any of its
    aspects, so a client holding either form is understood."""
    entry, site = entry_behind(node), site_of(node)
    if (
        entry is None
        or site is None
        or entry.content_model != PROOFREAD_PAGE_CONTENT_MODEL
    ):
        return None
    return ProofreadPageRef(site, entry, store.index_of(entry))


def site_of(node: WsNode) -> Site | None:
    match node:
        case SiteDir(site=site) | NamespaceDir(site=site) | TitleNode(site=site):
            return site
        case AspectLeaf() | PagesDir():
            return node.site
        case _:
            return None


def title_node(
    store: PageStore,
    path: WikiPath,
    site: Site,
    namespaces: SiteNamespaces,
    ns: NsView,
    rest: str,
) -> TitleNode | None:
    """The node for `rest` in [ns]: held by the cache, or synthetic because
    subpages of it are."""
    full = ns.title(rest)
    entry = store.entry(site, full)
    if entry is None and not (ns.subpages and store.has_titles_under(site, f"{full}/")):
        return None
    return TitleNode(WikiPath.parse(path.node_path), site, namespaces, ns, rest, entry)


def resolve(store: PageStore, raw_path: str) -> WsNode:
    path = WikiPath.parse(raw_path)
    parts = path.segments

    if not parts:
        return RootDir(path)
    if len(parts) < 2:
        return Missing(path)

    site = store.site(parts[0], parts[1])
    if site is None:
        return Missing(path)
    namespaces = store.site_namespaces(site)
    if len(parts) == 2:
        return SiteDir(path, site, namespaces)

    ns = namespaces.by_segment(path.namespace_segment)
    if ns is None:
        return Missing(path)

    rest = path.title_rest
    if not rest:
        # `/f/c/ns/@aspect` has no title for the aspect to belong to.
        if len(parts) == 3:
            return NamespaceDir(path, site, namespaces, ns)
        return Missing(path)

    node = title_node(store, path, site, namespaces, ns, rest)
    if node is None:
        return Missing(path)

    aspect = path.aspect
    if aspect is None:
        return node

    if node.entry is None:
        return Missing(path)
    match aspect:
        case "wikitext" | "props":
            return AspectLeaf(path, node, aspect)
        case "pages" if node.is_index:
            return PagesDir(path, node)
        case _:
            return Missing(path)
