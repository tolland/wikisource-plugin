from __future__ import annotations

from dataclasses import dataclass

from wtbot.model import Site
from wtbot.vfs.paths import WikiPath
from wtbot.vfs.store import PROOFREAD_INDEX_CONTENT_MODEL, Entry, PageStore

"""Typed resolution of wikisource:// paths.

`resolve()` is the single place that classifies a path against the synthetic
ProofreadPage tree:

    /                                        RootDir
    /{family}/{code}                         SiteDir
    /{family}/{code}/{Index title}           IndexDir      (dual role: container...)
    /{family}/{code}/{Index title}/wikitext  IndexWikitext (...and content)
    /.../{Index title}/Pages                 PagesDir
    /.../{Index title}/Pages/{Page title}    PageLeaf
    /.../{Index title}/{subpage}             IndexAssetLeaf (styles.css, ...)

Every VFS operation (stat / list / read / write) resolves first and then
match/cases on the node type, so the tree shape is defined exactly once.
Nodes carry the ORM rows the resolver already fetched; operations must not
re-query what the resolver proved to exist.
"""


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
    index: Entry


@dataclass(frozen=True, slots=True)
class IndexWikitext:
    """The synthetic `wikitext` leaf under an IndexDir — the content half."""

    path: WikiPath
    site: Site
    index: Entry


@dataclass(frozen=True, slots=True)
class PagesDir:
    """Synthetic container grouping the index's Page: leaves. No underlying
    wiki page, hence no stable_id."""

    path: WikiPath
    site: Site
    index: Entry


@dataclass(frozen=True, slots=True)
class PageLeaf:
    path: WikiPath
    site: Site
    page: Entry


@dataclass(frozen=True, slots=True)
class IndexAssetLeaf:
    """Index-namespace subpage of the index (styles.css and friends).
    `name` is the path relative to the index dir; the page title is
    `{index_title}/{name}`."""

    path: WikiPath
    site: Site
    page: Entry
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
    | IndexAssetLeaf
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

    index_page = store.entry(site, index_title)
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

    joined = "/".join(rest)
    # Index-namespace subpage asset
    asset = store.entry(site, f"{index_title}/{joined}")
    if asset is None or asset.content_model == PROOFREAD_INDEX_CONTENT_MODEL:
        return Missing(path)
    return IndexAssetLeaf(path, site, asset, joined)
