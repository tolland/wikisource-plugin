import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from wtbot.annotation_store import SqlBoxLinkStore
from wtbot.main import create_app
from wtbot.model import BoxRangeLink, Page, Site
from wtbot.model.index_meta import IndexMeta
from wtbot.model.namespace import NsRole
from wtbot.model.page_meta import PageMeta

"""Tests for box→range links: the SQL-backed store and the /pages/box-links
API surface, including the cascades that keep a link from outliving either
of its endpoints (the box, or the text range it targets)."""

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Tractatus.djvu"
PAGE_TITLE = "Page:Tractatus.djvu/1"
PAGE_PATH = f"/{FAMILY}/{CODE}/{INDEX}/Pages/{PAGE_TITLE}"


def _seed(engine) -> int:
    """Site + index + one proofread page; returns the page pk."""
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
                page_count=1,
            )
        )
        page = Page(
            site_pk=site.pk,
            title=PAGE_TITLE,
            namespace_role=NsRole.page,
            content_model="proofread-page",
            revid=42,
        )
        s.add(page)
        s.flush()
        s.add(
            PageMeta(
                page_pk=page.pk,
                index_title=INDEX,
                page_number=1,
                source_image_url="https://wiki.example/img/Tractatus.djvu/page1.jpg",
            )
        )
        s.commit()
        return page.pk


@pytest.fixture
def client(engine):
    app = create_app(engine=engine)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def page_pk(engine) -> int:
    return _seed(engine)


def _put_box(client, annotation_id: str):
    body = {"x": 10, "y": 20, "width": 30, "height": 40}
    return client.put(
        f"/pages/annotations/{annotation_id}", params={"path": PAGE_PATH}, json=body
    )


def _put_anchor(client, annotation_id: str):
    body = {"text_start": 0, "text_end": 5}
    return client.put(
        f"/pages/text-anchors/{annotation_id}", params={"path": PAGE_PATH}, json=body
    )


def _put_link(client, box_id: str, range_id: str):
    return client.put(
        f"/pages/box-links/{box_id}",
        params={"path": PAGE_PATH},
        json={"range_annotation_id": range_id},
    )


def _links(client):
    return client.get("/pages/box-links", params={"path": PAGE_PATH}).json()["links"]


# -- SqlBoxLinkStore -------------------------------------------------------------


def test_store_upsert_inserts_then_repoints(engine, page_pk):
    with Session(engine) as s:
        store = SqlBoxLinkStore(s)
        store.upsert(
            BoxRangeLink(
                page_pk=page_pk, box_annotation_id="b1", range_annotation_id="r1"
            )
        )
        [row] = store.list_for_page(page_pk)
        assert (row.box_annotation_id, row.range_annotation_id) == ("b1", "r1")

        store.upsert(
            BoxRangeLink(
                page_pk=page_pk, box_annotation_id="b1", range_annotation_id="r2"
            )
        )
        [row] = store.list_for_page(page_pk)
        assert row.range_annotation_id == "r2"


def test_store_delete_and_delete_for_range(engine, page_pk):
    with Session(engine) as s:
        store = SqlBoxLinkStore(s)
        for box in ("b1", "b2"):
            store.upsert(
                BoxRangeLink(
                    page_pk=page_pk, box_annotation_id=box, range_annotation_id="r1"
                )
            )
        assert store.delete(page_pk, "b1") is True
        assert store.delete(page_pk, "b1") is False
        # Both remaining links target r1 — a range cascade removes them all.
        store.upsert(
            BoxRangeLink(
                page_pk=page_pk, box_annotation_id="b3", range_annotation_id="r9"
            )
        )
        assert store.delete_for_range(page_pk, "r1") == 1
        assert store.delete_for_range(page_pk, "r1") == 0
        [row] = store.list_for_page(page_pk)
        assert row.box_annotation_id == "b3"


# -- /pages/box-links ------------------------------------------------------------


def test_link_upsert_and_list(client, page_pk):
    _put_box(client, "b1")
    _put_anchor(client, "r1")
    resp = _put_link(client, "b1", "r1")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"box_annotation_id": "b1", "range_annotation_id": "r1"}
    assert _links(client) == [{"box_annotation_id": "b1", "range_annotation_id": "r1"}]


def test_link_requires_existing_range(client, page_pk):
    _put_box(client, "b1")
    assert _put_link(client, "b1", "missing").status_code == 404


def test_relink_repoints_the_box(client, page_pk):
    _put_box(client, "b1")
    _put_anchor(client, "r1")
    _put_anchor(client, "r2")
    _put_link(client, "b1", "r1")
    _put_link(client, "b1", "r2")
    assert _links(client) == [{"box_annotation_id": "b1", "range_annotation_id": "r2"}]


def test_delete_link(client, page_pk):
    _put_box(client, "b1")
    _put_anchor(client, "r1")
    _put_link(client, "b1", "r1")
    resp = client.delete("/pages/box-links/b1", params={"path": PAGE_PATH})
    assert resp.status_code == 204
    assert _links(client) == []
    assert (
        client.delete("/pages/box-links/b1", params={"path": PAGE_PATH}).status_code
        == 404
    )


def test_deleting_anchor_drops_links_to_it(client, page_pk):
    _put_anchor(client, "r1")
    for box in ("b1", "b2"):
        _put_box(client, box)
        _put_link(client, box, "r1")
    resp = client.delete("/pages/text-anchors/r1", params={"path": PAGE_PATH})
    assert resp.status_code == 204
    assert _links(client) == []


def test_deleting_box_drops_its_link(client, page_pk):
    _put_box(client, "b1")
    _put_anchor(client, "r1")
    _put_link(client, "b1", "r1")
    resp = client.delete("/pages/annotations/b1", params={"path": PAGE_PATH})
    assert resp.status_code == 204
    assert _links(client) == []
    # The range itself survives — only the link is invalidated.
    anchors = client.get("/pages/text-anchors", params={"path": PAGE_PATH}).json()
    assert [a["annotation_id"] for a in anchors["anchors"]] == ["r1"]
