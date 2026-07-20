import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.annotation_store import SqlAnnotationStore, SqlTextAnchorStore
from wtbot.main import create_app
from wtbot.model import (
    AnnotationCategory,
    Page,
    ScanAnnotation,
    Site,
    TextTargetAnchor,
)
from wtbot.model.index_meta import IndexMeta
from wtbot.model.namespace import NsRole
from wtbot.model.page_meta import PageMeta

"""Tests for scan annotations: the SQL-backed stores (boxes and text anchors
as independent halves joined by annotation_id) and the /pages/annotations +
/pages/text-anchors API surfaces."""

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


def _put_box(client, annotation_id: str, **overrides):
    body = {"x": 10, "y": 20, "width": 30, "height": 40, **overrides}
    return client.put(
        f"/pages/annotations/{annotation_id}", params={"path": PAGE_PATH}, json=body
    )


def _put_anchor(client, annotation_id: str, **overrides):
    body = {"text_start": 0, "text_end": 5, **overrides}
    return client.put(
        f"/pages/text-anchors/{annotation_id}", params={"path": PAGE_PATH}, json=body
    )


# -- SqlAnnotationStore ----------------------------------------------------------


def test_store_upsert_inserts_then_updates(engine, page_pk):
    with Session(engine) as s:
        store = SqlAnnotationStore(s)
        store.upsert(
            ScanAnnotation(
                page_pk=page_pk,
                annotation_id="a1",
                x=10,
                y=20,
                width=30,
                height=40,
                label="l",
                category=AnnotationCategory.body,
            )
        )
        [row] = store.list_for_page(page_pk)
        assert (row.x, row.y, row.width, row.height) == (10, 20, 30, 40)
        assert row.category is AnnotationCategory.body

        store.upsert(
            ScanAnnotation(
                page_pk=page_pk, annotation_id="a1", x=1, y=2, width=3, height=4
            )
        )
        [row] = store.list_for_page(page_pk)
        assert (row.x, row.y, row.width, row.height) == (1, 2, 3, 4)
        assert row.label is None and row.category is None
        assert len(store.list_for_page(page_pk)) == 1


def test_store_delete(engine, page_pk):
    with Session(engine) as s:
        store = SqlAnnotationStore(s)
        store.upsert(
            ScanAnnotation(
                page_pk=page_pk, annotation_id="a", x=0, y=0, width=1, height=1
            )
        )
        assert store.delete(page_pk, "a") is True
        assert store.list_for_page(page_pk) == []
        assert store.delete(page_pk, "a") is False


def test_anchor_store_is_independent_of_boxes(engine, page_pk):
    with Session(engine) as s:
        anchors = SqlTextAnchorStore(s)
        anchors.upsert(
            TextTargetAnchor(
                page_pk=page_pk, annotation_id="a1", text_start=3, text_end=9
            )
        )
        # No box exists for a1 — the text-first workflow is legitimate.
        assert SqlAnnotationStore(s).list_for_page(page_pk) == []
        [row] = anchors.list_for_page(page_pk)
        assert (row.text_start, row.text_end) == (3, 9)

        anchors.upsert(
            TextTargetAnchor(
                page_pk=page_pk,
                annotation_id="a1",
                text_start=7,
                text_end=7,
                anchor_revid=42,
            )
        )
        [row] = anchors.list_for_page(page_pk)
        assert (row.text_start, row.text_end, row.anchor_revid) == (7, 7, 42)
        assert anchors.delete(page_pk, "a1") is True
        assert anchors.delete(page_pk, "a1") is False


# -- /pages/annotations ----------------------------------------------------------


def test_upsert_and_list_boxes(client, page_pk):
    resp = _put_box(client, "a1", label="para 1", category="paragraph")
    assert resp.status_code == 200, resp.text
    assert resp.json()["category"] == "paragraph"

    listing = client.get("/pages/annotations", params={"path": PAGE_PATH}).json()
    [ann] = listing["annotations"]
    assert ann["id"] == "a1"
    assert (ann["x"], ann["width"]) == (10.0, 30.0)
    assert ann["label"] == "para 1"
    assert ann["category"] == "paragraph"


def test_upsert_rejects_unknown_category(client, page_pk):
    assert _put_box(client, "a1", category="marginalia").status_code == 422


def test_delete_box_also_drops_its_anchor(client, engine, page_pk):
    _put_box(client, "a1")
    _put_anchor(client, "a1")
    resp = client.delete("/pages/annotations/a1", params={"path": PAGE_PATH})
    assert resp.status_code == 204
    assert client.get("/pages/annotations", params={"path": PAGE_PATH}).json() == {
        "annotations": []
    }
    assert client.get("/pages/text-anchors", params={"path": PAGE_PATH}).json() == {
        "anchors": []
    }
    assert (
        client.delete("/pages/annotations/a1", params={"path": PAGE_PATH}).status_code
        == 404
    )


def test_non_page_path_is_404(client, page_pk):
    for url in ["/pages/annotations", "/pages/text-anchors"]:
        resp = client.get(url, params={"path": f"/{FAMILY}/{CODE}"})
        assert resp.status_code == 404


# -- /pages/text-anchors ---------------------------------------------------------


def test_anchor_upsert_and_list(client, page_pk):
    resp = _put_anchor(client, "a1", text_start=5, text_end=9, anchor_revid=42)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "annotation_id": "a1",
        "text_start": 5,
        "text_end": 9,
        "anchor_revid": 42,
    }

    listing = client.get("/pages/text-anchors", params={"path": PAGE_PATH}).json()
    [anchor] = listing["anchors"]
    assert anchor["annotation_id"] == "a1"


def test_anchor_insertion_point(client, page_pk):
    resp = _put_anchor(client, "a1", text_start=7, text_end=7)
    assert resp.status_code == 200
    anchor = resp.json()
    assert anchor["text_start"] == anchor["text_end"] == 7


def test_anchor_validates_range(client, page_pk):
    assert _put_anchor(client, "a1", text_start=9, text_end=5).status_code == 422
    assert _put_anchor(client, "a1", text_start=-1, text_end=5).status_code == 422


def test_anchor_delete(client, engine, page_pk):
    _put_anchor(client, "a1")
    resp = client.delete("/pages/text-anchors/a1", params={"path": PAGE_PATH})
    assert resp.status_code == 204
    with Session(engine) as s:
        assert s.exec(select(TextTargetAnchor)).first() is None
    assert (
        client.delete("/pages/text-anchors/a1", params={"path": PAGE_PATH}).status_code
        == 404
    )
