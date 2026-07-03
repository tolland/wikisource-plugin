from __future__ import annotations

from dataclasses import dataclass

from wtbot.model import Page, Site
from wtbot.vfs.paths import WikiPath
from wtbot.vfs.store import PROOFREAD_INDEX_CONTENT_MODEL, PageStore

"""Typed resolution of wikisource:// paths.

`resolve()` is the single place that classifies a path against the synthetic
ProofreadPage tree:

    /                                        RootDir
    /{family}/{code}                         SiteDir
    /{family}/{code}/{Index title}           IndexDir      (dual role: container...)
    /{family}/{code}/{Index title}/wikitext  IndexWikitext (...and content)
    /.../{Index title}/Pages                 PagesDir
    /.../{Index title}/Pages/{Page title}    PageLeaf
    /.../{Index title}/{File title}          FileDir       (dual role again)
    /.../{Index title}/{File title}/wikitext FileWikitext
    /.../{Index title}/{File title}/blob     FileBlobLeaf
    /.../{Index title}/{subpage}             IndexAssetLeaf (styles.css, ...)
    /.../{Index title}/Templates             StubDir
    /.../{Index title}/TranscludedFiles      StubDir

Every VFS operation (stat / list / read / write) resolves first and then
match/cases on the node type, so the tree shape is defined exactly once.
Nodes carry the ORM rows the resolver already fetched; operations must not
re-query what the resolver proved to exist.
"""

STUB_CONTAINERS = ("Templates", "TranscludedFiles")


@dataclass(frozen=True, slots=True)
class RootDir:
    path: WikiPath


@dataclass(frozen=True, slots=True)
class SiteDir:
    path: WikiPath
    site: Site


@dataclass(frozen=True, slots=True)
class IndexDir:
    """An Index: title as a directory — the container half of its dual role."""

    path: WikiPath
    site: Site
    index: Page


@dataclass(frozen=True, slots=True)
class IndexWikitext:
    """The synthetic `wikitext` leaf under an IndexDir — the content half."""

    path: WikiPath
    site: Site
    index: Page


@dataclass(frozen=True, slots=True)
class PagesDir:
    """Synthetic container grouping the index's Page: leaves. No underlying
    wiki page, hence no stable_id."""

    path: WikiPath
    site: Site
    index: Page


@dataclass(frozen=True, slots=True)
class PageLeaf:
    path: WikiPath
    site: Site
    page: Page


@dataclass(frozen=True, slots=True)
class FileDir:
    path: WikiPath
    site: Site
    file_page: Page


@dataclass(frozen=True, slots=True)
class FileWikitext:
    path: WikiPath
    site: Site
    file_page: Page


@dataclass(frozen=True, slots=True)
class FileBlobLeaf:
    path: WikiPath
    site: Site
    file_page: Page


@dataclass(frozen=True, slots=True)
class IndexAssetLeaf:
    """Index-namespace subpage of the index (styles.css and friends).
    `name` is the path relative to the index dir; the page title is
    `{index_title}/{name}`."""

    path: WikiPath
    site: Site
    page: Page
    name: str


@dataclass(frozen=True, slots=True)
class StubDir:
    path: WikiPath
    name: str


@dataclass(frozen=True, slots=True)
class Missing:
    path: WikiPath


type WsNode = (
    RootDir
    | SiteDir
    | IndexDir
    | IndexWikitext
    | PagesDir
    | PageLeaf
    | FileDir
    | FileWikitext
    | FileBlobLeaf
    | IndexAssetLeaf
    | StubDir
    | Missing
)


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
    if len(parts) == 2:
        return SiteDir(path, site)

    index_title = path.index_title
    rest = path.rest

    index_page = store.page(site, index_title)
    if index_page is None:
        return Missing(path)

    if not rest:
        return IndexDir(path, site, index_page)

    if rest == ("wikitext",):
        return IndexWikitext(path, site, index_page)

    if rest[0] == "Pages":
        if len(rest) == 1:
            return PagesDir(path, site, index_page)
        # proofread_page applies the membership filters: an arbitrary title
        # addressed under this index's Pages/ must not resolve just because
        # it exists somewhere on the site.
        page = store.proofread_page(site, "/".join(rest[1:]), index_title)
        return PageLeaf(path, site, page) if page is not None else Missing(path)

    if len(rest) == 1 and rest[0] in STUB_CONTAINERS:
        return StubDir(path, rest[0])

    # File: leaf (wikitext/blob) beneath the File: dir
    if rest[-1] in ("wikitext", "blob") and "/".join(rest[:-1]).startswith("File:"):
        file_page = store.page(site, "/".join(rest[:-1]))
        if file_page is None:
            return Missing(path)
        if rest[-1] == "wikitext":
            return FileWikitext(path, site, file_page)
        return FileBlobLeaf(path, site, file_page)

    joined = "/".join(rest)
    if joined.startswith("File:"):
        file_page = store.page(site, joined)
        return (
            FileDir(path, site, file_page) if file_page is not None else Missing(path)
        )

    # Index-namespace subpage asset
    asset = store.page(site, f"{index_title}/{joined}")
    if asset is None or asset.content_model == PROOFREAD_INDEX_CONTENT_MODEL:
        return Missing(path)
    return IndexAssetLeaf(path, site, asset, joined)
