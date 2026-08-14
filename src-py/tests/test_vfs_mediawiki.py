import pytest

from wtbot.model import Page, Site
from wtbot.model.wiki.namespace import Namespace, NsRole
from wtbot.model.wikisource.page_meta import PageMeta
from wtbot.vfs.mediawiki import MediaWikiVfs, title_namespace_name
from wtbot.vfs.store import PageStore
from wtbot.vfs.wikisource import WikisourceVfs

"""Tests for the mediawiki layer: title namespace parsing and the
Namespace.subpages rule, including how the rule surfaces in the wikisource
overlay's Index listing (subpage-only assets follow the flag; assets linked
via index_title are listed regardless).
"""

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Foo.djvu"
_INDEX_PATH = f"/{FAMILY}/{CODE}/{INDEX}"

# Linked via index_title AND a title-wise subpage — the common case.
LINKED_SUBPAGE = f"{INDEX}/styles.css"
# A title-wise subpage with no index_title link.
UNLINKED_SUBPAGE = f"{INDEX}/legacy.css"


@pytest.fixture
def site(session) -> Site:
    site = Site(family=FAMILY, code=CODE)
    session.add(site)
    session.commit()
    session.refresh(site)

    session.add(
        Page(
            site_pk=site.pk,
            title=INDEX,
            namespace_role=NsRole.index,
            content_model="proofread-index",
        )
    )
    linked = Page(
        site_pk=site.pk,
        title=LINKED_SUBPAGE,
        namespace_role=NsRole.index,
        content_model="sanitized-css",
    )
    session.add(linked)
    session.flush()
    session.add(PageMeta(page_pk=linked.pk, index_title=INDEX))
    session.add(
        Page(
            site_pk=site.pk,
            title=UNLINKED_SUBPAGE,
            namespace_role=NsRole.index,
            content_model="sanitized-css",
        )
    )
    session.commit()
    return site


def _add_index_namespace(session, site, *, subpages: bool) -> None:
    session.add(
        Namespace(
            site_pk=site.pk,
            key=252,
            canonical_name="Index",
            local_name="Index",
            role=NsRole.index,
            subpages=subpages,
        )
    )
    session.commit()


def test_title_namespace_name():
    assert title_namespace_name("Index:Foo.djvu") == "Index"
    assert title_namespace_name("Page:Foo.djvu/1") == "Page"
    assert title_namespace_name("Mainspace title") == ""


def test_subpages_permissive_without_namespace_map(session, site):
    """Namespace rows come from siteinfo; before any fetch the map is empty
    and subpages cannot be ruled out."""
    mw = MediaWikiVfs(PageStore(session))
    assert mw.subpages_enabled(site, INDEX) is True
    titles = [p.title for p in mw.subpages(site, INDEX)]
    assert titles == [UNLINKED_SUBPAGE, LINKED_SUBPAGE]


def test_subpages_respect_namespace_flag(session, site):
    _add_index_namespace(session, site, subpages=False)
    mw = MediaWikiVfs(PageStore(session))
    assert mw.subpages_enabled(site, INDEX) is False
    assert mw.subpages(site, INDEX) == []


def test_subpages_enabled_namespace_lists_them(session, site):
    _add_index_namespace(session, site, subpages=True)
    mw = MediaWikiVfs(PageStore(session))
    titles = [p.title for p in mw.subpages(site, INDEX)]
    assert titles == [UNLINKED_SUBPAGE, LINKED_SUBPAGE]


def test_overlay_index_children_follow_subpage_flag(session, site):
    """With subpages disabled, a subpage-only asset disappears from the
    Index dir, but an asset explicitly linked via index_title stays."""
    _add_index_namespace(session, site, subpages=False)
    names = [c.name for c in WikisourceVfs(session).list_children(_INDEX_PATH).children]
    assert "styles.css" in names  # linked via index_title
    assert "legacy.css" not in names  # subpage-only


def test_overlay_index_children_include_subpages_when_enabled(session, site):
    _add_index_namespace(session, site, subpages=True)
    names = [c.name for c in WikisourceVfs(session).list_children(_INDEX_PATH).children]
    assert "styles.css" in names
    assert "legacy.css" in names


def test_proofread_pages_match_across_underscore_space(session):
    """MediaWiki treats '_' and ' ' as equivalent in titles, so a fetched
    Page: (wiki's literal spaced title) and a fan-out stub (generated from the
    underscore request title) can carry different index_title spellings for
    the same Index. The membership query must match both."""
    site = Site(family=FAMILY, code=CODE)
    session.add(site)
    session.commit()
    session.refresh(site)

    spaced = "Index:Unreported RTT Pathway Removals at MSE FT.pdf"
    underscored = "Index:Unreported_RTT_Pathway_Removals_at_MSE_FT.pdf"

    real = Page(
        site_pk=site.pk,
        title="Page:Unreported RTT Pathway Removals at MSE FT.pdf/5",
        namespace_role=NsRole.page,
        content_model="proofread-page",
    )
    stub = Page(
        site_pk=site.pk,
        title="Page:Unreported_RTT_Pathway_Removals_at_MSE_FT.pdf/1",
        namespace_role=NsRole.page,
        content_model="proofread-page",
    )
    session.add(real)
    session.add(stub)
    session.flush()
    # Real page linked with spaces; stub linked with underscores.
    session.add(PageMeta(page_pk=real.pk, index_title=spaced, page_number=5))
    session.add(PageMeta(page_pk=stub.pk, index_title=underscored, page_number=1))
    session.commit()

    store = PageStore(session)
    # Querying by either spelling returns both members.
    for query_title in (spaced, underscored):
        titles = {p.title for p in store.proofread_pages(site, query_title)}
        assert titles == {real.title, stub.title}, query_title
