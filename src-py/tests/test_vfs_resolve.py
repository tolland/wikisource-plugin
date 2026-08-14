import pytest
from conftest import add_proofread_meta
from sqlmodel import Session

from wtbot.model import Page, Site
from wtbot.model.wiki.namespace import NsRole
from wtbot.vfs.nodes import (
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
from wtbot.vfs.store import PageStore

"""Unit tests for wtbot.vfs.nodes.resolve — path → typed node classification.

These are the table-driven tests the resolver extraction exists for: no HTTP
stack, one seeded session, one assertion per path shape.
"""

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu"
FILE = "File:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu"
PAGE_1 = "Page:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu/1"

_INDEX_PATH = f"/{FAMILY}/{CODE}/{INDEX}"


@pytest.fixture
def store(engine):
    with Session(engine) as s:
        site = Site(family=FAMILY, code=CODE)
        s.add(site)
        s.commit()
        s.refresh(site)
        s.add(
            Page(
                site_pk=site.pk,
                title=INDEX,
                namespace_role=NsRole.index,
                content_model="proofread-index",
            )
        )
        styles = Page(
            site_pk=site.pk,
            title=f"{INDEX}/styles.css",
            namespace_role=NsRole.index,
            content_model="sanitized-css",
        )
        s.add(styles)
        s.add(
            Page(
                site_pk=site.pk,
                title=FILE,
                namespace_role=NsRole.file,
                content_model="wikitext",
            )
        )
        page_1 = Page(
            site_pk=site.pk,
            title=PAGE_1,
            namespace_role=NsRole.page,
            content_model="proofread-page",
        )
        s.add(page_1)
        s.flush()
        add_proofread_meta(s, page_pk=page_1.pk, index_title=INDEX, page_number=1)
        s.commit()
        yield PageStore(s)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", RootDir),
        ("/wikisource", Missing),
        (f"/{FAMILY}/{CODE}", SiteDir),
        ("/nosuch/xx", Missing),
        (_INDEX_PATH, IndexDir),
        (f"{_INDEX_PATH}/", IndexDir),
        (f"/{FAMILY}/{CODE}/Index:NoSuch", Missing),
        (f"{_INDEX_PATH}/wikitext", IndexWikitext),
        (f"{_INDEX_PATH}/Pages", PagesDir),
        (f"{_INDEX_PATH}/Pages/{PAGE_1}", PageLeaf),
        # exists on the site, but is not a Page: of this index
        (f"{_INDEX_PATH}/Pages/{FILE}", Missing),
        (f"{_INDEX_PATH}/Pages/Page:NoSuch.djvu/9", Missing),
        (f"{_INDEX_PATH}/Templates", StubDir),
        (f"{_INDEX_PATH}/TranscludedFiles", StubDir),
        (f"{_INDEX_PATH}/Templates/deeper", Missing),
        (f"{_INDEX_PATH}/{FILE}", FileDir),
        (f"{_INDEX_PATH}/{FILE}/wikitext", FileWikitext),
        (f"{_INDEX_PATH}/{FILE}/blob", FileBlobLeaf),
        (f"{_INDEX_PATH}/File:NoSuch.djvu", Missing),
        (f"{_INDEX_PATH}/styles.css", IndexAssetLeaf),
        (f"{_INDEX_PATH}/nosuch.css", Missing),
    ],
)
def test_resolve_classifies(store, path, expected):
    assert type(resolve(store, path)) is expected


def test_resolve_carries_underlying_pages(store):
    page_leaf = resolve(store, f"{_INDEX_PATH}/Pages/{PAGE_1}")
    assert isinstance(page_leaf, PageLeaf)
    assert page_leaf.page.title == PAGE_1

    # Dual role: the synthetic wikitext leaf is backed by the Index page itself.
    wikitext = resolve(store, f"{_INDEX_PATH}/wikitext")
    assert isinstance(wikitext, IndexWikitext)
    assert wikitext.index.title == INDEX

    file_wikitext = resolve(store, f"{_INDEX_PATH}/{FILE}/wikitext")
    assert isinstance(file_wikitext, FileWikitext)
    assert file_wikitext.file_page.title == FILE

    asset = resolve(store, f"{_INDEX_PATH}/styles.css")
    assert isinstance(asset, IndexAssetLeaf)
    assert asset.name == "styles.css"
    assert asset.page.title == f"{INDEX}/styles.css"
