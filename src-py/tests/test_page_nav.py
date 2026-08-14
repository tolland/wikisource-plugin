import pytest
from conftest import add_proofread_meta
from sqlmodel import Session

from wtbot.model import Page, Site
from wtbot.model.wiki.namespace import NsRole
from wtbot.model.wikisource.index_meta import IndexMeta

"""Tests for GET /pages/nav — the split editor's page-navigation metadata:
prev/next sibling resolution in Pages/-listing order, first/last edges, and
the non-page-path guard."""

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Tractatus.djvu"
INDEX_PATH = f"/{FAMILY}/{CODE}/{INDEX}"


def _page_path(title: str) -> str:
    return f"{INDEX_PATH}/Pages/{title}"


def _seed(engine, page_numbers: list[int]) -> None:
    with Session(engine) as s:
        site = Site(family=FAMILY, code=CODE)
        s.add(site)
        s.flush()
        index = Page(
            site_pk=site.pk,
            title=INDEX,
            namespace_role=NsRole.index,
            content_model="proofread-index",
        )
        s.add(index)
        s.flush()
        s.add(
            IndexMeta(
                page_pk=index.pk,
                site_pk=site.pk,
                short_name="Tractatus",
                page_count=len(page_numbers),
            )
        )
        for n in page_numbers:
            page = Page(
                site_pk=site.pk,
                title=f"Page:Tractatus.djvu/{n}",
                namespace_role=NsRole.page,
                content_model="proofread-page",
            )
            s.add(page)
            s.flush()
            add_proofread_meta(s, page_pk=page.pk, index_title=INDEX, page_number=n)
        s.commit()


@pytest.fixture
def seeded(engine):
    _seed(engine, [1, 2, 3])


def test_nav_middle_page_has_both_neighbors(client, seeded):
    r = client.get("/pages/nav", params={"path": _page_path("Page:Tractatus.djvu/2")})
    assert r.status_code == 200
    nav = r.json()
    assert nav["current"]["title"] == "Page:Tractatus.djvu/2"
    assert nav["current"]["page_number"] == 2
    assert nav["index_title"] == INDEX
    assert nav["index_path"] == INDEX_PATH
    assert nav["page_count"] == 3
    assert nav["position"] == 2
    assert nav["total"] == 3
    assert nav["prev"]["path"] == _page_path("Page:Tractatus.djvu/1")
    assert nav["prev"]["page_number"] == 1
    assert nav["next"]["path"] == _page_path("Page:Tractatus.djvu/3")
    assert nav["next"]["page_number"] == 3


def test_nav_first_page_has_no_prev(client, seeded):
    r = client.get("/pages/nav", params={"path": _page_path("Page:Tractatus.djvu/1")})
    assert r.status_code == 200
    nav = r.json()
    assert nav["prev"] is None
    assert nav["next"]["title"] == "Page:Tractatus.djvu/2"


def test_nav_last_page_has_no_next(client, seeded):
    r = client.get("/pages/nav", params={"path": _page_path("Page:Tractatus.djvu/3")})
    assert r.status_code == 200
    nav = r.json()
    assert nav["prev"]["title"] == "Page:Tractatus.djvu/2"
    assert nav["next"] is None


def test_nav_orders_by_page_number_not_seed_order(client, engine):
    # Sparse, out-of-order numbering: neighbors follow page_number order.
    _seed(engine, [10, 2, 7])
    r = client.get("/pages/nav", params={"path": _page_path("Page:Tractatus.djvu/7")})
    assert r.status_code == 200
    nav = r.json()
    assert nav["prev"]["title"] == "Page:Tractatus.djvu/2"
    assert nav["next"]["title"] == "Page:Tractatus.djvu/10"


def test_nav_404_for_non_page_path(client, seeded):
    assert client.get("/pages/nav", params={"path": INDEX_PATH}).status_code == 404
    assert (
        client.get(
            "/pages/nav", params={"path": _page_path("Page:Other.djvu/1")}
        ).status_code
        == 404
    )
