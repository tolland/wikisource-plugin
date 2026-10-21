import pytest

from wtbot.vfs.namespaces import MAIN_SEGMENT, SiteNamespaces
from wtbot.vfs.paths import (
    WikiPath,
    aspect_path,
    child_path,
    decode_segment,
    encode_segment,
)

"""Path grammar: `/{family}/{code}/{namespace}/{title...}[/@aspect]`."""


def test_aspect_is_the_trailing_at_segment():
    path = WikiPath.parse("/wikisource/en/Book/Virtues and vices/Ch 1/@props")
    assert path.aspect == "props"
    assert path.node_segments == (
        "wikisource",
        "en",
        "Book",
        "Virtues and vices",
        "Ch 1",
    )
    assert path.title_rest == "Virtues and vices/Ch 1"
    assert path.node_path == "/wikisource/en/Book/Virtues and vices/Ch 1"


@pytest.mark.parametrize(
    "raw",
    [
        "/wikisource/en/Book/Foo",
        "/wikisource/en/Book",
        "/wikisource/en/Book/@",
        # an aspect needs a title before it; here the `@x` is the namespace slot
        "/wikisource/en/@x",
        # only the last segment can be an aspect
        "/wikisource/en/Book/@props/Foo",
    ],
)
def test_no_aspect(raw):
    assert WikiPath.parse(raw).aspect is None or raw.endswith("/@")


def test_leading_at_and_percent_in_titles_are_escaped():
    assert encode_segment("@home") == "%40home"
    assert encode_segment("%40") == "%2540"
    assert encode_segment("a@b") == "a@b"
    for segment in ("@home", "%40", "%25x", "plain", "a@b", ""):
        assert decode_segment(encode_segment(segment)) == segment

    path = WikiPath.parse("/wikisource/en/(Main)/%40home/@wikitext")
    assert path.aspect == "wikitext"
    assert path.title_rest == "@home"


def test_builders():
    assert child_path("/f/c/Book", "@x") == "/f/c/Book/%40x"
    assert aspect_path("/f/c/Book/Foo/", "props") == "/f/c/Book/Foo/@props"


def test_title_to_path_round_trips_through_the_namespace_map():
    namespaces = SiteNamespaces.from_rows([])
    cases = {
        "Index:Foo.pdf": "/w/en/Index/Foo.pdf",
        "Page:Foo.djvu/171": "/w/en/Page/Foo.djvu/171",
        "Faust: Part One": f"/w/en/{MAIN_SEGMENT}/Faust: Part One",
        "@odd title": f"/w/en/{MAIN_SEGMENT}/%40odd title",
    }
    for title, expected in cases.items():
        assert namespaces.node_path("w", "en", title) == expected
        assert namespaces.node_path("w", "en", title, aspect="wikitext") == (
            f"{expected}/@wikitext"
        )
        path = WikiPath.parse(expected)
        ns = namespaces.by_segment(path.namespace_segment)
        assert ns is not None
        assert ns.title(path.title_rest) == title
