import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from ocrapi.client import FakeOcrClient, OcrError
from wtbot.api.ocr import get_client_builder
from wtbot.main import create_app
from wtbot.model import Page, Site
from wtbot.model.index_meta import IndexMeta
from wtbot.model.namespace import NsRole
from wtbot.model.page_meta import PageMeta

"""Tests for wtbot's thin /pages/ocr wrapper: resolving a page path to a
scope (site family/code) and a backend-reachable image URL, then
delegating to the standalone ocrapi package for everything else. Backend
*configuration* goes through the mounted /ocr sub-app directly (the same
TestClient reaches it, since it's mounted on this app) rather than any
wtbot-side CRUD -- there isn't any; see ocrapi.api for that.

ocrapi's own generic behavior (crop threading, prompt defaults, backend
resolution, the Wikimedia wire format) is covered in test_ocrapi.py and
not re-tested here -- these tests are only about the page/site resolution
this module adds on top."""

FAMILY = "wikisource"
CODE = "en"
SCOPE = f"{FAMILY}/{CODE}"
INDEX = "Index:Hertz.pdf"
PAGE_TITLE = "Page:Hertz.pdf/103"
PAGE_PATH = f"/{FAMILY}/{CODE}/{INDEX}/Pages/{PAGE_TITLE}"
SOURCE_URL = "https://wiki.example/img/Hertz.pdf/page103-500px.jpg"


def _seed(engine) -> int:
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
                page_pk=index.pk, site_pk=site.pk, short_name="Hertz", page_count=1
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
                page_number=103,
                source_image_url=SOURCE_URL,
            )
        )
        s.commit()
        return page.pk


@pytest.fixture
def fake_ocr() -> FakeOcrClient:
    return FakeOcrClient(text="Die Principien der Mechanik")


@pytest.fixture
def client(engine, fake_ocr):
    app = create_app(engine=engine)
    app.dependency_overrides[get_client_builder] = lambda: (lambda config: fake_ocr)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def page_pk(engine) -> int:
    return _seed(engine)


def _put_config(client, name: str, **overrides):
    body = {"kind": "wikimedia", "base_url": "https://ocr.wiki.lan", **overrides}
    # The standalone app mounted at /ocr, reached through the same client.
    return client.put(f"/ocr/config/{name}", params={"scope": SCOPE}, json=body)


# -- backend discovery by page path ----------------------------------------------


def test_backends_scoped_by_site_family_code(client, page_pk):
    _put_config(client, "wmocr")
    _put_config(client, "gemini", kind="token_api")
    listing = client.get("/pages/ocr/backends", params={"path": PAGE_PATH}).json()
    assert [b["name"] for b in listing["backends"]] == ["wmocr", "gemini"]


def test_backends_do_not_leak_across_scopes(client, page_pk):
    _put_config(client, "wmocr")
    # A config under a different scope must not show up for this page.
    client.put(
        "/ocr/config/other-site-backend",
        params={"scope": "wikisource/de"},
        json={"kind": "wikimedia", "base_url": "https://ocr.wiki.lan"},
    )
    listing = client.get("/pages/ocr/backends", params={"path": PAGE_PATH}).json()
    assert [b["name"] for b in listing["backends"]] == ["wmocr"]


def test_backends_unknown_page_is_404(client):
    resp = client.get("/pages/ocr/backends", params={"path": "/wikisource/en/nope"})
    assert resp.status_code == 404


# -- /pages/ocr/run ---------------------------------------------------------------


def test_run_translates_image_url_and_threads_box_as_crop(client, page_pk, fake_ocr):
    _put_config(client, "wmocr")
    resp = client.post(
        "/pages/ocr/run",
        json={
            "path": PAGE_PATH,
            "box": {"x": 233.24, "y": 555.78, "width": 321.68, "height": 77.17},
        },
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["backend"] == "wmocr"
    assert out["text"] == "Die Principien der Mechanik"

    sent = fake_ocr.last_request
    # The backend gets the wiki-side URL from PageMeta, not a localhost one.
    assert sent.image_url == SOURCE_URL
    crop = sent.crop
    assert (crop.x, crop.y, crop.width, crop.height) == (233, 556, 322, 77)


def test_run_without_box_has_no_crop(client, page_pk, fake_ocr):
    _put_config(client, "wmocr")
    client.post("/pages/ocr/run", json={"path": PAGE_PATH})
    assert fake_ocr.last_request.crop is None


def test_run_annotation_id_and_image_base64_pass_through(client, page_pk, fake_ocr):
    _put_config(client, "gemini", kind="token_api", default_prompt="default prompt")
    resp = client.post(
        "/pages/ocr/run",
        json={
            "path": PAGE_PATH,
            "backend": "gemini",
            "annotation_id": "b1",
            "image_base64": "aGVsbG8=",
            "prompt": "custom latex instructions",
            "langs": ["de"],
        },
    )
    assert resp.status_code == 200, resp.text
    sent = fake_ocr.last_request
    assert sent.image_base64 == "aGVsbG8="
    assert sent.prompt == "custom latex instructions"
    assert sent.langs == ["de"]


def test_run_unknown_backend_is_404(client, page_pk):
    _put_config(client, "wmocr")
    resp = client.post("/pages/ocr/run", json={"path": PAGE_PATH, "backend": "nope"})
    assert resp.status_code == 404


def test_run_without_config_is_404(client, page_pk):
    resp = client.post("/pages/ocr/run", json={"path": PAGE_PATH})
    assert resp.status_code == 404
    assert "no OCR backend" in resp.json()["detail"]


def test_run_unknown_page_is_404(client):
    resp = client.post("/pages/ocr/run", json={"path": "/wikisource/en/nope"})
    assert resp.status_code == 404


def test_run_maps_ocr_error_to_502(engine, page_pk):
    class FailingClient:
        def recognize(self, request):
            raise OcrError("engine exploded")

    app = create_app(engine=engine)
    app.dependency_overrides[get_client_builder] = lambda: (
        lambda config: FailingClient()
    )
    with TestClient(app) as c:
        _put_config(c, "wmocr")
        resp = c.post("/pages/ocr/run", json={"path": PAGE_PATH})
    assert resp.status_code == 502
    assert "engine exploded" in resp.json()["detail"]
