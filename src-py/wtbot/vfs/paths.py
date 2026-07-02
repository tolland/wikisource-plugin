from __future__ import annotations

from dataclasses import dataclass

"""Path parsing for the VFS.

A VFS path is `/{family}/{code}/{title-ish segments...}`. Segments beyond
the site prefix may themselves contain `/` as part of a MediaWiki title
(`Page:Foo.djvu/171`), so parsing stops at splitting — how many trailing
segments form one title is decided by the resolver, which knows the tree
shape (and, later, by the mediawiki layer's namespace subpage rules).
"""


@dataclass(frozen=True, slots=True)
class WikiPath:
    """A parsed VFS path. `raw` is echoed back in responses verbatim;
    `normalized` is the canonical slash-joined form used to build child
    paths so listings are stable regardless of how the caller spelled the
    parent path."""

    raw: str
    segments: tuple[str, ...]

    @classmethod
    def parse(cls, raw: str) -> WikiPath:
        return cls(raw=raw, segments=tuple(s for s in raw.strip("/").split("/") if s))

    @property
    def normalized(self) -> str:
        return "/" + "/".join(self.segments) if self.segments else "/"

    @property
    def is_root(self) -> bool:
        return not self.segments

    @property
    def family(self) -> str:
        return self.segments[0]

    @property
    def code(self) -> str:
        return self.segments[1]

    @property
    def index_title(self) -> str:
        return self.segments[2]

    @property
    def rest(self) -> tuple[str, ...]:
        """Segments below the index title."""
        return self.segments[3:]
