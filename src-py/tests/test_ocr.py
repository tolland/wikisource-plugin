import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from wtbot.api.ocr import get_client_builder
from wtbot.main import create_app
from wtbot.model import Page, Site
from wtbot.model.index_meta import IndexMeta
from wtbot.model.namespace import NsRole
from wtbot.model.page_meta import PageMeta
from wtbot.ocr import FakeOcrClient, OcrCrop, OcrError, OcrRequest, WikimediaOcrClient

"""Tests for the OCR wrapper: per-site backend config CRUD, backend
discovery by page path, and /ocr/run — including the image-URL translation
(the backend gets the wiki-side URL, never a sidecar-local one), prompt
threading, and backend selection. The client seam is exercised through
FakeOcrClient via the get_client_builder dependency override."""

FAMILY = "wikisource"
CODE = "en"
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
    return client.put(
        f"/ocr/config/{name}", params={"family": FAMILY, "code": CODE}, json=body
    )


# -- config CRUD -----------------------------------------------------------------


def test_config_upsert_and_list(client, page_pk):
    resp = _put_config(
        client, "wmocr", default_engine="tesseract", default_langs=["en", "de"]
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["kind"] == "wikimedia"
    assert out["default_langs"] == ["en", "de"]
    assert out["supports_prompt"] is False
    assert "api_token" not in out  # tokens are never echoed

    listing = client.get("/ocr/config", params={"family": FAMILY, "code": CODE}).json()
    assert [b["name"] for b in listing["backends"]] == ["wmocr"]

    # Upsert replaces in place.
    _put_config(client, "wmocr", default_engine="google")
    listing = client.get("/ocr/config", params={"family": FAMILY, "code": CODE}).json()
    [row] = listing["backends"]
    assert row["default_engine"] == "google"


def test_config_delete(client, page_pk):
    _put_config(client, "wmocr")
    resp = client.delete("/ocr/config/wmocr", params={"family": FAMILY, "code": CODE})
    assert resp.status_code == 204
    assert (
        client.delete(
            "/ocr/config/wmocr", params={"family": FAMILY, "code": CODE}
        ).status_code
        == 404
    )


def test_config_unknown_site_is_404(client):
    assert _put_config(client, "x").status_code == 404


# -- backend discovery by page path ---------------------------------------------


def test_backends_lists_only_enabled(client, page_pk):
    _put_config(client, "wmocr")
    _put_config(client, "gemini", kind="token_api", api_token="s3cret", enabled=False)
    listing = client.get("/ocr/backends", params={"path": PAGE_PATH}).json()
    assert [b["name"] for b in listing["backends"]] == ["wmocr"]


def test_token_api_backend_advertises_capabilities(client, page_pk):
    _put_config(client, "gemini", kind="token_api", default_prompt="transcribe latex")
    [b] = client.get("/ocr/backends", params={"path": PAGE_PATH}).json()["backends"]
    assert b["supports_prompt"] is True
    assert b["supports_segment"] is True


# -- /ocr/run --------------------------------------------------------------------


def test_run_translates_image_url_and_applies_defaults(client, page_pk, fake_ocr):
    _put_config(client, "wmocr", default_engine="tesseract", default_langs=["en"])
    resp = client.post("/ocr/run", json={"path": PAGE_PATH})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["backend"] == "wmocr"
    assert out["text"] == "Die Principien der Mechanik"

    sent = fake_ocr.last_request
    # The backend gets the wiki-side URL from PageMeta, not a localhost one.
    assert sent.image_url == SOURCE_URL
    assert sent.engine == "tesseract"
    assert sent.langs == ["en"]
    assert sent.crop is None  # no box, whole page


def test_run_threads_the_bounding_box_as_a_crop(client, page_pk, fake_ocr):
    _put_config(client, "wmocr")
    resp = client.post(
        "/ocr/run",
        json={
            "path": PAGE_PATH,
            "box": {"x": 233.24, "y": 555.78, "width": 321.68, "height": 77.17},
        },
    )
    assert resp.status_code == 200, resp.text
    crop = fake_ocr.last_request.crop
    assert (crop.x, crop.y, crop.width, crop.height) == (233, 556, 322, 77)


def test_run_request_overrides_defaults_and_threads_prompt(client, page_pk, fake_ocr):
    _put_config(
        client,
        "gemini",
        kind="token_api",
        default_prompt="default prompt",
        default_engine=None,
    )
    resp = client.post(
        "/ocr/run",
        json={
            "path": PAGE_PATH,
            "backend": "gemini",
            "image_base64": "aGVsbG8=",
            "prompt": "custom latex instructions",
            "langs": ["de"],
            "annotation_id": "b1",
            "box": {"x": 1, "y": 2, "width": 3, "height": 4},
        },
    )
    assert resp.status_code == 200, resp.text
    sent = fake_ocr.last_request
    assert sent.image_base64 == "aGVsbG8="
    assert sent.prompt == "custom latex instructions"
    assert sent.langs == ["de"]


def test_run_falls_back_to_default_prompt(client, page_pk, fake_ocr):
    _put_config(client, "gemini", kind="token_api", default_prompt="default prompt")
    client.post(
        "/ocr/run",
        json={"path": PAGE_PATH, "backend": "gemini", "image_base64": "aGVsbG8="},
    )
    assert fake_ocr.last_request.prompt == "default prompt"


def test_run_unknown_backend_is_404(client, page_pk):
    _put_config(client, "wmocr")
    resp = client.post("/ocr/run", json={"path": PAGE_PATH, "backend": "nope"})
    assert resp.status_code == 404


def test_run_without_config_is_404(client, page_pk):
    resp = client.post("/ocr/run", json={"path": PAGE_PATH})
    assert resp.status_code == 404
    assert "no OCR backend configured" in resp.json()["detail"]


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
        resp = c.post("/ocr/run", json={"path": PAGE_PATH})
    assert resp.status_code == 502
    assert "engine exploded" in resp.json()["detail"]


# -- WikimediaOcrClient wire format ---------------------------------------------


def test_wikimedia_client_builds_the_documented_request(monkeypatch):
    captured = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"engine": "tesseract", "text": "recognized"}

    def fake_get(url, params=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return Resp()

    monkeypatch.setattr("wtbot.ocr.requests.get", fake_get)
    client = WikimediaOcrClient("https://ocr.wiki.lan/")
    result = client.recognize(
        OcrRequest(
            image_url="https://img.example/p.jpg",
            engine="tesseract",
            langs=["en", "de"],
            crop=OcrCrop(x=3, y=101, width=649, height=168),
        )
    )
    assert result.text == "recognized"
    assert captured["url"] == "https://ocr.wiki.lan/api.php"
    assert ("image", "https://img.example/p.jpg") in captured["params"]
    assert ("engine", "tesseract") in captured["params"]
    assert ("langs[]", "en") in captured["params"]
    assert ("langs[]", "de") in captured["params"]
    assert ("crop[x]", "3") in captured["params"]
    assert ("crop[y]", "101") in captured["params"]
    assert ("crop[width]", "649") in captured["params"]
    assert ("crop[height]", "168") in captured["params"]


def test_wikimedia_client_requires_an_image_url():
    client = WikimediaOcrClient("https://ocr.wiki.lan")
    with pytest.raises(OcrError):
        client.recognize(OcrRequest(image_url=None))


def test_wikimedia_client_surfaces_api_errors(monkeypatch):
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"error": "no engine"}

    monkeypatch.setattr("wtbot.ocr.requests.get", lambda *a, **k: Resp())
    client = WikimediaOcrClient("https://ocr.wiki.lan")
    with pytest.raises(OcrError, match="no engine"):
        client.recognize(OcrRequest(image_url="https://img.example/p.jpg"))
