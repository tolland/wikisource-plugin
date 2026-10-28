import pytest
from conftest import add_proofread_meta, make_page
from sqlmodel import Session

from wtbot.model import Site
from wtbot.model.wiki.namespace import Namespace
from wtbot.vfs.nodes import (
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
from wtbot.vfs.store import PageStore

"""Unit tests for wtbot.vfs.nodes.resolve — path → typed node classification.

Table-driven: no HTTP stack, one seeded session, one assertion per path shape.
"""

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu"
FILE = "File:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu"
PAGE_1 = "Page:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu/1"
BOOK = "Book:Virtues and vices"
CHAPTER = f"{BOOK}/Chapter 1"
DEEP = f"{BOOK}/Part 2/Section 3"
COLON_TITLE = "Faust: Part One"

_SITE = f"/{FAMILY}/{CODE}"
_INDEX_PATH = f"{_SITE}/Index/Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu"
_BOOK_PATH = f"{_SITE}/Book/Virtues and vices"


@pytest.fixture
def store(engine):
    with Session(engine) as s:
        site = Site(family=FAMILY, code=CODE)
        s.add(site)
        s.commit()
        s.refresh(site)
        # A fetched siteinfo lists every namespace, so a partial map is not a
        # real case: seed the ones the fixtures use.
        for key, name, subpages in (
            (6, "File", False),
            (250, "Page", False),
            (252, "Index", True),
            (3000, "Book", True),
        ):
            s.add(
                Namespace(
                    site_pk=site.pk,
                    key=key,
                    canonical_name=name,
                    local_name=name,
                    subpages=subpages,
                )
            )
        s.add(make_page(site_pk=site.pk, title=INDEX, content_model="proofread-index"))
        s.add(
            make_page(
                site_pk=site.pk,
                title=f"{INDEX}/styles.css",
                content_model="sanitized-css",
            )
        )
        file_page = make_page(site_pk=site.pk, title=FILE, content_model="wikitext")
        s.add(file_page)
        page_1 = make_page(
            site_pk=site.pk, title=PAGE_1, content_model="proofread-page"
        )
        s.add(page_1)
        for title in (BOOK, CHAPTER, DEEP, COLON_TITLE):
            s.add(make_page(site_pk=site.pk, title=title, content_model="wikitext"))
        s.flush()
        add_proofread_meta(s, page_pk=page_1.pk, index_title=INDEX, page_number=1)
        file_page.address.namespace_key = 6
        s.commit()
        yield PageStore(s)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", RootDir),
        ("/wikisource", Missing),
        (_SITE, SiteDir),
        ("/nosuch/xx", Missing),
        (f"{_SITE}/Index", NamespaceDir),
        (f"{_SITE}/Nonsense", Missing),
        (f"{_SITE}/(Main)", NamespaceDir),
        (_INDEX_PATH, TitleNode),
        (f"{_INDEX_PATH}/", TitleNode),
        (f"{_SITE}/Index/NoSuch", Missing),
        (f"{_INDEX_PATH}/@wikitext", AspectLeaf),
        (f"{_INDEX_PATH}/@props", AspectLeaf),
        (f"{_INDEX_PATH}/@pages", PagesDir),
        (f"{_INDEX_PATH}/@nosuch", Missing),
        # a subpage is a node of its own, with its own aspects
        (f"{_INDEX_PATH}/styles.css", TitleNode),
        (f"{_INDEX_PATH}/styles.css/@wikitext", AspectLeaf),
        (f"{_INDEX_PATH}/styles.css/@pages", Missing),
        (f"{_INDEX_PATH}/nosuch.css", Missing),
        # Page: has no subpages, so the slash belongs to the title
        (
            f"{_SITE}/Page/Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu/1",
            TitleNode,
        ),
        (
            f"{_SITE}/Page/Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu/1/@wikitext",
            AspectLeaf,
        ),
        (
            f"{_SITE}/Page/Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu",
            Missing,
        ),
        # any namespace is browsable, not only Index/Page
        (
            f"{_SITE}/File/Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu",
            TitleNode,
        ),
        (_BOOK_PATH, TitleNode),
        (f"{_BOOK_PATH}/@wikitext", AspectLeaf),
        (f"{_BOOK_PATH}/Chapter 1", TitleNode),
        (f"{_BOOK_PATH}/Chapter 1/@props", AspectLeaf),
        # synthetic intermediate: nothing holds Book:...Part 2, titles are below it
        (f"{_BOOK_PATH}/Part 2", TitleNode),
        (f"{_BOOK_PATH}/Part 2/@wikitext", Missing),
        (f"{_BOOK_PATH}/Part 2/Section 3/@wikitext", AspectLeaf),
        # a colon without a namespace stays a mainspace title
        (f"{_SITE}/(Main)/Faust: Part One", TitleNode),
        (f"{_SITE}/(Main)/Faust: Part One/@wikitext", AspectLeaf),
        # an aspect needs a title to belong to
        (f"{_SITE}/Index/@wikitext", Missing),
    ],
)
def test_resolve_classifies(store, path, expected):
    assert type(resolve(store, path)) is expected


def test_resolve_carries_underlying_pages(store):
    page = resolve(
        store,
        f"{_SITE}/Page/Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu/1/@wikitext",
    )
    assert isinstance(page, AspectLeaf)
    assert page.entry.name == PAGE_1
    assert store.index_of(page.entry).name == INDEX

    # Dual role: the index title is a container, and its content an aspect.
    wikitext = resolve(store, f"{_INDEX_PATH}/@wikitext")
    assert isinstance(wikitext, AspectLeaf)
    assert wikitext.entry.name == INDEX

    asset = resolve(store, f"{_INDEX_PATH}/styles.css")
    assert isinstance(asset, TitleNode)
    assert asset.entry is not None
    assert asset.entry.name == f"{INDEX}/styles.css"
    assert (
        asset.rest
        == "Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu/styles.css"
    )


def test_synthetic_node_has_no_entry_or_aspects(store):
    node = resolve(store, f"{_BOOK_PATH}/Part 2")
    assert isinstance(node, TitleNode)
    assert node.entry is None
    assert aspect_names(node.entry) == []


def test_aspect_names_by_content_model(store):
    index = resolve(store, _INDEX_PATH)
    assert isinstance(index, TitleNode)
    assert aspect_names(index.entry) == ["wikitext", "props", "pages"]
    book = resolve(store, _BOOK_PATH)
    assert isinstance(book, TitleNode)
    assert aspect_names(book.entry) == ["wikitext", "props"]


def test_unknown_prefix_resolves_as_mainspace_when_map_is_empty(engine):
    """Before siteinfo is fetched, `Book:` is not a known namespace; the title
    is still reachable as a mainspace title, because the whole title is what is
    looked up."""
    with Session(engine) as s:
        site = Site(family=FAMILY, code=CODE)
        s.add(site)
        s.commit()
        s.refresh(site)
        s.add(make_page(site_pk=site.pk, title=BOOK, content_model="wikitext"))
        s.commit()
        store = PageStore(s)
        assert isinstance(resolve(store, f"{_SITE}/(Main)/{BOOK}"), TitleNode)
