from __future__ import annotations

from dataclasses import dataclass

from wtbot.model.wiki.namespace import Namespace
from wtbot.vfs.paths import child_path, encode_segment

"""A site's namespaces as the VFS tree's second level.

Titles split into `(namespace, rest)`. The first colon only counts when the
prefix names one of the site's namespaces -- a mainspace title such as
`Faust: Part One` has a colon and no namespace -- so the split is decided
against the Namespace map (populated from siteinfo), never by the colon alone.

The main namespace has no prefix and is shown as `(Main)`. That segment can
never collide with a title: the namespace level holds namespaces only.

A site whose siteinfo has not been fetched has no Namespace rows. The VFS then
falls back to the standard MediaWiki and ProofreadPage names so a cache built
before the first siteinfo fetch is still browsable; the answer for an unknown
prefix is simply "main namespace", which still resolves, because the full
title is what is looked up.
"""

MAIN_SEGMENT = "(Main)"

# Canonical names of namespaces, and whether each supports subpages, used
# only while a site has no Namespace rows.
_FALLBACK_SUBPAGES: dict[str, bool] = {
    "Talk": True,
    "User": True,
    "User talk": True,
    "Project": True,
    "Project talk": True,
    "File": False,
    "File talk": True,
    "MediaWiki": False,
    "MediaWiki talk": True,
    "Template": True,
    "Template talk": True,
    "Help": True,
    "Help talk": True,
    "Category": True,
    "Category talk": True,
    "Page": False,
    "Page talk": True,
    "Index": True,
    "Index talk": True,
    "Author": True,
    "Author talk": True,
    "Portal": True,
    "Portal talk": True,
    "Module": False,
    "Module talk": True,
}

PAGE_NAMESPACE_CANONICAL = "Page"


def _normal(name: str) -> str:
    return name.replace("_", " ").strip()


@dataclass(frozen=True, slots=True)
class NsView:
    """One namespace, as the tree sees it."""

    name: str
    """The path segment, and the title prefix without its colon."""
    canonical_name: str
    key: int | None
    subpages: bool

    @property
    def is_main(self) -> bool:
        return self.name == MAIN_SEGMENT

    @property
    def prefix(self) -> str:
        """The title prefix including its colon; empty for the main namespace."""
        return "" if self.is_main else f"{self.name}:"

    @property
    def listed(self) -> bool:
        """Shown as a child of the site. The Page namespace holds one title
        per scanned page, which is browsed through its Index instead; it stays
        addressable by path and listable directly."""
        return self.canonical_name != PAGE_NAMESPACE_CANONICAL

    def title(self, rest: str) -> str:
        return f"{self.prefix}{rest}"


def _main(subpages: bool = True) -> NsView:
    return NsView(MAIN_SEGMENT, MAIN_SEGMENT, 0, subpages)


class SiteNamespaces:
    def __init__(self, views: list[NsView], aliases: dict[str, NsView]) -> None:
        self._views = views
        self._by_name = aliases
        self.main = next(v for v in views if v.is_main)

    @classmethod
    def from_rows(cls, rows: list[Namespace]) -> SiteNamespaces:
        views: list[NsView] = []
        aliases: dict[str, NsView] = {}
        main = _main()
        if rows:
            for row in rows:
                if row.key == 0:
                    main = _main(row.subpages)
                    continue
                view = NsView(
                    _normal(row.local_name or row.canonical_name),
                    _normal(row.canonical_name),
                    row.key,
                    row.subpages,
                )
                views.append(view)
                aliases[view.name] = view
                aliases[view.canonical_name] = view
        else:
            for canonical, subpages in _FALLBACK_SUBPAGES.items():
                view = NsView(canonical, canonical, None, subpages)
                views.append(view)
                aliases[canonical] = view
        views.insert(0, main)
        return cls(views, aliases)

    def all(self) -> list[NsView]:
        return list(self._views)

    def others(self) -> list[NsView]:
        """Every namespace but the main one."""
        return [v for v in self._views if not v.is_main]

    def by_segment(self, segment: str) -> NsView | None:
        """The namespace a path segment names, by display or canonical name."""
        if segment == MAIN_SEGMENT:
            return self.main
        return self._by_name.get(_normal(segment))

    def split(self, title: str) -> tuple[NsView, str]:
        """`(namespace, rest)` of a full title."""
        prefix, sep, rest = title.partition(":")
        if sep:
            view = self._by_name.get(_normal(prefix))
            if view is not None:
                return view, rest
        return self.main, title

    def node_path(
        self, family: str, code: str, title: str, aspect: str | None = None
    ) -> str:
        """The VFS path of a full wiki title, in the wiki's spelling (spaces):
        `_` and a space are one character to MediaWiki, and the path of a page
        must not depend on which a caller used."""
        ns, rest = self.split(title.replace("_", " "))
        path = f"/{family}/{code}/{encode_segment(ns.name)}"
        for segment in rest.split("/"):
            path = child_path(path, segment)
        return f"{path}/@{aspect}" if aspect else path
