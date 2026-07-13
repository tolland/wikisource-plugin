import xml.etree.ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from wtbot.annotation_svg import SvgAnnotation, SvgAnnotationStore
from wtbot.main import create_app
from wtbot.model import AnnotationAnchor, Page, Site
from wtbot.model.index_meta import IndexMeta
from wtbot.model.namespace import NsRole
from wtbot.model.page_meta import PageMeta

"""Tests for scan annotations: the SvgAnnotationStore round trip (including
transform-aware reads of externally edited documents) and the /pages/
annotations API — typed list/upsert/delete merged with text anchors, and
the raw SVG import/export face with dangling-anchor reporting."""

FAMILY = "wikisource"
CODE = "en"
INDEX = "Index:Tractatus.djvu"
PAGE_TITLE = "Page:Tractatus.djvu/1"
PAGE_PATH = f"/{FAMILY}/{CODE}/{INDEX}/Pages/{PAGE_TITLE}"

IMAGE_SIZE = {"image_width": 1000, "image_height": 800}


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
def blob_root(tmp_path):
    return tmp_path / "blobs"


@pytest.fixture
def client(engine, blob_root):
    app = create_app(engine=engine, blob_root=blob_root)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def page_pk(engine) -> int:
    return _seed(engine)


def _put(client, annotation_id: str, **overrides):
    body = {"x": 10, "y": 20, "width": 30, "height": 40, **IMAGE_SIZE, **overrides}
    return client.put(
        f"/pages/annotations/{annotation_id}", params={"path": PAGE_PATH}, json=body
    )


# -- SvgAnnotationStore ----------------------------------------------------------


def test_store_round_trip_and_document_shape(blob_root, page_pk):
    store = SvgAnnotationStore(blob_root)
    store.upsert_rect(
        page_pk,
        SvgAnnotation(
            id="a1", shape="rect", x=10, y=20, width=30, height=40, label="l"
        ),
        image_size=(1000, 800),
        image_href="../page_images/scan.jpg",
    )

    root = ET.parse(store.path_for(page_pk)).getroot()
    assert root.get("viewBox") == "0 0 1000 800"
    svg_ns = "{http://www.w3.org/2000/svg}"
    assert root.find(f"{svg_ns}image").get("href") == "../page_images/scan.jpg"

    [ann] = store.read(page_pk)
    assert ann == SvgAnnotation(
        id="a1", shape="rect", x=10.0, y=20.0, width=30.0, height=40.0, label="l"
    )


def test_store_upsert_updates_in_place_and_drops_transform(blob_root, page_pk):
    store = SvgAnnotationStore(blob_root)
    store.upsert_rect(
        page_pk,
        SvgAnnotation(id="a1", shape="rect", x=10, y=20, width=30, height=40),
        image_size=(1000, 800),
    )
    # Simulate an external editor translating the rect.
    doc = store.read_document(page_pk).replace(
        'id="a1"', 'id="a1" transform="translate(100,0)"'
    )
    store.write_document(page_pk, doc)
    [moved] = store.read(page_pk)
    assert moved.x == 110.0

    # A typed write is authoritative: transform dropped, geometry replaced.
    store.upsert_rect(
        page_pk, SvgAnnotation(id="a1", shape="rect", x=1, y=2, width=3, height=4)
    )
    [ann] = store.read(page_pk)
    assert (ann.x, ann.y, ann.width, ann.height) == (1.0, 2.0, 3.0, 4.0)
    assert len(store.read(page_pk)) == 1


def test_store_reads_foreign_shapes_and_nested_transforms(blob_root, page_pk):
    store = SvgAnnotationStore(blob_root)
    store.write_document(
        page_pk,
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 800"
                width="264.58mm" height="211.66mm">
             <g id="annotations" transform="translate(5,5)">
               <rect id="r" x="0" y="0" width="10" height="10"/>
               <ellipse id="e" cx="500" cy="400" rx="50" ry="25"/>
             </g>
           </svg>""",
    )
    anns = {a.id: a for a in store.read(page_pk)}
    # Group transform applied; physical-unit width/height did not rescale.
    assert round(anns["r"].x) == 5 and round(anns["r"].y) == 5
    assert anns["e"].shape != "rect"
    assert round(anns["e"].x) == 455 and round(anns["e"].width) == 100


def test_store_requires_image_size_for_new_document(blob_root, page_pk):
    store = SvgAnnotationStore(blob_root)
    with pytest.raises(ValueError, match="image_size"):
        store.upsert_rect(
            page_pk, SvgAnnotation(id="a", shape="rect", x=0, y=0, width=1, height=1)
        )


def test_store_rejects_unparseable_document(blob_root, page_pk):
    store = SvgAnnotationStore(blob_root)
    with pytest.raises(ValueError, match="SVG"):
        store.write_document(page_pk, "<svg unclosed")
    assert not store.exists(page_pk)


def test_store_delete(blob_root, page_pk):
    store = SvgAnnotationStore(blob_root)
    store.upsert_rect(
        page_pk,
        SvgAnnotation(id="a", shape="rect", x=0, y=0, width=1, height=1),
        image_size=(100, 100),
    )
    assert store.delete(page_pk, "a") is True
    assert store.read(page_pk) == []
    assert store.delete(page_pk, "a") is False


# -- typed API -------------------------------------------------------------------


def test_upsert_and_list_with_anchor(client, page_pk):
    resp = _put(client, "a1", label="para 1", text_start=5, text_end=9, anchor_revid=42)
    assert resp.status_code == 200, resp.text
    assert resp.json()["text_start"] == 5

    listing = client.get("/pages/annotations", params={"path": PAGE_PATH}).json()
    [ann] = listing["annotations"]
    assert ann["id"] == "a1"
    assert ann["shape"] == "rect"
    assert (ann["x"], ann["width"]) == (10.0, 30.0)
    assert ann["label"] == "para 1"
    assert (ann["text_start"], ann["text_end"], ann["anchor_revid"]) == (5, 9, 42)
    assert listing["dangling_anchor_ids"] == []


def test_upsert_insertion_point_anchor(client, page_pk):
    resp = _put(client, "a1", text_start=7, text_end=7)
    assert resp.status_code == 200
    ann = resp.json()
    assert ann["text_start"] == ann["text_end"] == 7


def test_upsert_without_anchor_then_link_then_unlink(client, engine, page_pk):
    assert _put(client, "a1").status_code == 200
    [ann] = client.get("/pages/annotations", params={"path": PAGE_PATH}).json()[
        "annotations"
    ]
    assert ann["text_start"] is None

    assert _put(client, "a1", text_start=0, text_end=3).status_code == 200
    with Session(engine) as s:
        assert s.exec(select(AnnotationAnchor)).one().text_end == 3

    assert _put(client, "a1").status_code == 200  # anchor fields omitted: unlink
    with Session(engine) as s:
        assert s.exec(select(AnnotationAnchor)).first() is None


def test_upsert_validates_anchor_range(client, page_pk):
    assert _put(client, "a1", text_start=9, text_end=5).status_code == 422
    assert _put(client, "a1", text_start=4).status_code == 422


def test_first_upsert_without_image_size_conflicts(client, page_pk):
    resp = client.put(
        "/pages/annotations/a1",
        params={"path": PAGE_PATH},
        json={"x": 1, "y": 1, "width": 2, "height": 2},
    )
    assert resp.status_code == 409
    assert "image_size" in resp.json()["detail"]


def test_delete_annotation(client, page_pk):
    _put(client, "a1", text_start=0, text_end=1)
    assert (
        client.delete("/pages/annotations/a1", params={"path": PAGE_PATH}).status_code
        == 204
    )
    listing = client.get("/pages/annotations", params={"path": PAGE_PATH}).json()
    assert listing == {"annotations": [], "dangling_anchor_ids": []}
    assert (
        client.delete("/pages/annotations/a1", params={"path": PAGE_PATH}).status_code
        == 404
    )


def test_non_page_path_is_404(client, page_pk):
    for method, url in [
        ("get", "/pages/annotations"),
        ("get", "/pages/annotations/svg"),
    ]:
        resp = getattr(client, method)(url, params={"path": f"/{FAMILY}/{CODE}"})
        assert resp.status_code == 404


# -- raw SVG face ----------------------------------------------------------------


def test_svg_export_links_scan_raster(client, page_pk):
    _put(client, "a1")
    resp = client.get("/pages/annotations/svg", params={"path": PAGE_PATH})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert f'href="../page_images/{page_pk}-src.jpg"' in resp.text
    assert 'id="a1"' in resp.text


def test_svg_get_before_any_annotation_is_404(client, page_pk):
    resp = client.get("/pages/annotations/svg", params={"path": PAGE_PATH})
    assert resp.status_code == 404


def test_svg_import_round_trip_reports_dangling_anchor(client, page_pk):
    _put(client, "a1", text_start=0, text_end=5)
    _put(client, "a2")

    # Out-of-band edit: drop a1 (whose anchor should dangle), keep a2 moved.
    doc = client.get("/pages/annotations/svg", params={"path": PAGE_PATH}).text
    root = ET.fromstring(doc)
    group = root.find("{http://www.w3.org/2000/svg}g")
    rect_a1 = next(e for e in group if e.get("id") == "a1")
    group.remove(rect_a1)
    next(e for e in group if e.get("id") == "a2").set("x", "500")

    resp = client.put(
        "/pages/annotations/svg",
        params={"path": PAGE_PATH},
        content=ET.tostring(root),
    )
    assert resp.status_code == 200, resp.text
    listing = resp.json()
    [ann] = listing["annotations"]
    assert ann["id"] == "a2" and ann["x"] == 500.0
    assert listing["dangling_anchor_ids"] == ["a1"]


def test_svg_import_rejects_garbage(client, page_pk):
    resp = client.put(
        "/pages/annotations/svg", params={"path": PAGE_PATH}, content=b"not svg"
    )
    assert resp.status_code == 400
