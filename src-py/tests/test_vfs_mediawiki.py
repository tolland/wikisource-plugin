import pytest
from conftest import add_proofread_meta, make_page

from wtbot.model import Site
from wtbot.model.wiki.namespace import Namespace
from wtbot.vfs.store import PageStore
from wtbot.vfs.wikisource import WikisourceVfs

"""Tests for the Namespace.subpages rule and how it surfaces in the
wikisource overlay's tree (Index assets follow the ordinary subpage flag),
plus title matching across underscore/space spellings.
"""

FAMILY = "wikisource"
CODE = "en"
INDEX_NAME = "Foo.djvu"
INDEX = f"Index:{INDEX_NAME}"
_INDEX_PATH = f"/{FAMILY}/{CODE}/Index/{INDEX_NAME}"

LINKED_SUBPAGE = f"{INDEX}/styles.css"
UNLINKED_SUBPAGE = f"{INDEX}/legacy.css"


@pytest.fixture
def site(session) -> Site:
    site = Site(family=FAMILY, code=CODE)
    session.add(site)
    session.commit()
    session.refresh(site)

    session.add(
        make_page(
            site_pk=site.pk,
            title=INDEX,
            content_model="proofread-index",
        )
    )
    linked = make_page(
        site_pk=site.pk,
        title=LINKED_SUBPAGE,
        content_model="sanitized-css",
    )
    session.add(linked)
    session.add(
        make_page(
            site_pk=site.pk,
            title=UNLINKED_SUBPAGE,
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
            subpages=subpages,
        )
    )
    session.commit()


def _child_names(session, path: str) -> list[str]:
    return [c.name for c in WikisourceVfs(session).list_children(path).children]


def test_subpages_permissive_without_namespace_map(session, site):
    """Namespace rows come from siteinfo; before any fetch the map is empty
    and the standard names stand in, so Index subpages show."""
    names = _child_names(session, _INDEX_PATH)
    assert {"styles.css", "legacy.css"} <= set(names)


def test_subpages_follow_namespace_flag(session, site):
    """With subpages disabled the slash is part of the title: the Index has
    no subpage children, and the CSS titles are flat nodes of the namespace."""
    _add_index_namespace(session, site, subpages=False)
    names = _child_names(session, _INDEX_PATH)
    assert "styles.css" not in names
    assert "legacy.css" not in names
    flat = WikisourceVfs(session).list_children(f"/{FAMILY}/{CODE}/Index").children
    assert f"{_INDEX_PATH}/styles.css" in [c.path for c in flat]


def test_subpages_enabled_namespace_lists_them(session, site):
    _add_index_namespace(session, site, subpages=True)
    names = _child_names(session, _INDEX_PATH)
    assert "styles.css" in names
    assert "legacy.css" in names


def test_proofread_pages_match_across_underscore_space(session):
    """MediaWiki treats '_' and ' ' as equivalent in titles, so a fetched
    Page: (wiki's literal spaced title) and a fan-out stub (generated from the
    underscore request title) still resolve to the same Index key."""
    site = Site(family=FAMILY, code=CODE)
    session.add(site)
    session.commit()
    session.refresh(site)

    spaced = "Index:Unreported RTT Pathway Removals at MSE FT.pdf"
    underscored = "Index:Unreported_RTT_Pathway_Removals_at_MSE_FT.pdf"

    real = make_page(
        site_pk=site.pk,
        title="Page:Unreported RTT Pathway Removals at MSE FT.pdf/5",
        content_model="proofread-page",
    )
    stub = make_page(
        site_pk=site.pk,
        title="Page:Unreported_RTT_Pathway_Removals_at_MSE_FT.pdf/1",
        content_model="proofread-page",
    )
    session.add(real)
    session.add(stub)
    session.flush()
    # Both title spellings resolve to one Index Page identity.
    add_proofread_meta(session, page_pk=real.pk, index_title=spaced, page_number=5)
    add_proofread_meta(session, page_pk=stub.pk, index_title=underscored, page_number=1)
    session.commit()

    store = PageStore(session)
    # Querying by either spelling returns both members.
    for query_title in (spaced, underscored):
        titles = {p.name for p in store.proofread_pages(site, query_title)}
        assert titles == {real.address.title, stub.address.title}, query_title
