from __future__ import annotations

from dataclasses import dataclass

"""Path parsing for the VFS.

A VFS path is

    /{family}/{code}/{namespace}/{title segments...}[/@{aspect}]

`{namespace}` is the site's namespace name (or `(Main)` for the main
namespace); the title segments are the rest of the wiki title, split on `/`
(`Page:Foo.djvu/171` is `/Page/Foo.djvu/171`). Parsing stops at splitting --
whether trailing segments are subpages or one flat title is decided by the
resolver, against the namespace's `subpages` flag.

An *aspect* is a view of a title (its wikitext, its properties, ...). It is
the last segment, introduced by `@`. A title segment that itself starts with
`@` or `%` is escaped (`%40`, `%25`) so the two can never be confused.
"""

ASPECT_PREFIX = "@"
_ESCAPES = {"@": "%40", "%": "%25"}
_UNESCAPES = {v: k for k, v in _ESCAPES.items()}

FIRST_TITLE_SEGMENT = 3
"""Index of the first title segment: after family, code and namespace."""


def encode_segment(segment: str) -> str:
    """Escape a title segment for use in a path; only the leading character
    can be mistaken for syntax."""
    head = segment[:1]
    return _ESCAPES[head] + segment[1:] if head in _ESCAPES else segment


def decode_segment(segment: str) -> str:
    head = segment[:3]
    return _UNESCAPES[head] + segment[3:] if head in _UNESCAPES else segment


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
    def namespace_segment(self) -> str:
        return decode_segment(self.segments[2])

    @property
    def aspect(self) -> str | None:
        """The trailing `@aspect`, if the path has one. It must follow at
        least one title segment, so `/f/c/Index/@x` names the aspect `x` of a
        title only when a title precedes it."""
        if len(self.segments) <= FIRST_TITLE_SEGMENT:
            return None
        last = self.segments[-1]
        if last.startswith(ASPECT_PREFIX) and len(last) > 1:
            return last[1:]
        return None

    @property
    def node_segments(self) -> tuple[str, ...]:
        """The segments without the aspect."""
        if self.aspect is None:
            return self.segments
        return self.segments[:-1]

    @property
    def node_path(self) -> str:
        """The path of the title node this path addresses or belongs to."""
        return "/" + "/".join(self.node_segments)

    @property
    def title_rest(self) -> str:
        """The title below the namespace, slashes included and escapes
        undone: `Foo.djvu/171` for `/f/c/Page/Foo.djvu/171`. Empty when the
        path stops at the namespace (or earlier)."""
        return "/".join(
            decode_segment(s) for s in self.node_segments[FIRST_TITLE_SEGMENT:]
        )


def child_path(parent: str, segment: str) -> str:
    """`parent` with a title segment appended, escaped."""
    return f"{parent.rstrip('/')}/{encode_segment(segment)}"


def aspect_path(node_path: str, aspect: str) -> str:
    return f"{node_path.rstrip('/')}/{ASPECT_PREFIX}{aspect}"
