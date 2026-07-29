import pytest
from fastapi.testclient import TestClient

from ocrapi.api import get_client_builder
from ocrapi.app import create_ocr_app
from ocrapi.client import (
    FakeOcrClient,
    OcrCrop,
    OcrError,
    OcrRequest,
    WikimediaOcrClient,
)

"""Tests for the ocrapi HTTP surface and client logic: no wiki/page
concepts anywhere here, only image_url/image_base64 + an optional scope
string, which is the whole point -- this surface has to be usable by
something that has never heard of MediaWiki (e.g. an EXIF/metadata tool
sending a selected image over for recognition). Its persisted config
(OcrBackendConfig) is still wtbot's own app state (see
wtbot.model.ocr_backend), so these tests run against the same
Alembic-migrated `engine` fixture (conftest.py) every other wtbot test
uses. wtbot's page-path-aware wrapper on top is covered separately in
test_ocr.py."""


@pytest.fixture
def fake_ocr() -> FakeOcrClient:
    return FakeOcrClient(text="recognized text")


@pytest.fixture
def client(engine, fake_ocr):
    app = create_ocr_app(engine)
    app.dependency_overrides[get_client_builder] = lambda: (lambda config: fake_ocr)
    with TestClient(app) as c:
        yield c


def _put_config(client, name: str, scope: str | None = None, **overrides):
    body = {"kind": "wikimedia", "base_url": "https://ocr.example", **overrides}
    params = {"scope": scope} if scope is not None else {}
    return client.put(f"/config/{name}", params=params, json=body)


# -- health -------------------------------------------------------------------


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# -- config CRUD, default scope -------------------------------------------------


def test_config_upsert_uses_default_scope_when_unspecified(client):
    resp = _put_config(
        client, "wmocr", default_engine="tesseract", default_langs=["en", "de"]
    )
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["default_langs"] == ["en", "de"]
    assert out["supports_prompt"] is False
    assert out["has_api_token"] is False
    assert "api_token" not in out  # tokens are never echoed

    listing = client.get("/backends").json()  # default scope, no query
    assert [b["name"] for b in listing["backends"]] == ["wmocr"]


def test_config_update_preserves_omitted_write_only_token(client):
    _put_config(client, "gemini", kind="token_api", api_token="s3cret")
    response = _put_config(client, "gemini", kind="token_api")
    assert response.json()["has_api_token"] is True

    response = _put_config(client, "gemini", kind="token_api", api_token=None)
    assert response.json()["has_api_token"] is False


def test_config_upsert_replaces_in_place(client):
    _put_config(client, "wmocr", default_engine="tesseract")
    _put_config(client, "wmocr", default_engine="google")
    [row] = client.get("/backends").json()["backends"]
    assert row["default_engine"] == "google"


def test_config_scopes_are_independent(client):
    _put_config(client, "wmocr", scope="app-a")
    _put_config(client, "gemini", scope="app-b", kind="token_api")
    assert [
        b["name"]
        for b in client.get("/backends", params={"scope": "app-a"}).json()["backends"]
    ] == ["wmocr"]
    assert [
        b["name"]
        for b in client.get("/backends", params={"scope": "app-b"}).json()["backends"]
    ] == ["gemini"]


def test_backends_lists_only_enabled_by_default(client):
    _put_config(client, "wmocr")
    _put_config(client, "gemini", kind="token_api", enabled=False)
    listing = client.get("/backends").json()
    assert [b["name"] for b in listing["backends"]] == ["wmocr"]


def test_backends_enabled_only_false_includes_disabled(client):
    _put_config(client, "wmocr")
    _put_config(client, "gemini", kind="token_api", enabled=False)
    listing = client.get("/backends", params={"enabled_only": "false"}).json()
    assert [b["name"] for b in listing["backends"]] == ["wmocr", "gemini"]


def test_token_api_backend_advertises_capabilities(client):
    _put_config(client, "gemini", kind="token_api", default_prompt="transcribe latex")
    [b] = client.get("/backends").json()["backends"]
    assert b["supports_prompt"] is True
    assert b["supports_segment"] is True


def test_config_delete(client):
    _put_config(client, "wmocr")
    resp = client.delete("/config/wmocr")
    assert resp.status_code == 204
    assert client.delete("/config/wmocr").status_code == 404


# -- /run -----------------------------------------------------------------------


def test_run_with_image_url(client, fake_ocr):
    _put_config(client, "wmocr", default_engine="tesseract", default_langs=["en"])
    resp = client.post("/run", json={"image_url": "https://img.example/p.jpg"})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["backend"] == "wmocr"
    assert out["text"] == "recognized text"

    sent = fake_ocr.last_request
    assert sent.image_url == "https://img.example/p.jpg"
    assert sent.engine == "tesseract"
    assert sent.langs == ["en"]
    assert sent.crop is None


def test_run_with_image_base64(client, fake_ocr):
    _put_config(client, "gemini", kind="token_api")
    resp = client.post("/run", json={"backend": "gemini", "image_base64": "aGVsbG8="})
    assert resp.status_code == 200, resp.text
    assert fake_ocr.last_request.image_base64 == "aGVsbG8="


def test_run_requires_an_image(client):
    resp = client.post("/run", json={})
    assert resp.status_code == 422


def test_run_threads_crop(client, fake_ocr):
    _put_config(client, "wmocr")
    resp = client.post(
        "/run",
        json={
            "image_url": "https://img.example/p.jpg",
            "crop": {"x": 3.4, "y": 100.6, "width": 649.2, "height": 167.9},
        },
    )
    assert resp.status_code == 200, resp.text
    crop = fake_ocr.last_request.crop
    assert (crop.x, crop.y, crop.width, crop.height) == (3, 101, 649, 168)


def test_run_falls_back_to_default_prompt(client, fake_ocr):
    _put_config(client, "gemini", kind="token_api", default_prompt="default prompt")
    client.post("/run", json={"backend": "gemini", "image_base64": "aGVsbG8="})
    assert fake_ocr.last_request.prompt == "default prompt"


def test_run_request_prompt_overrides_default(client, fake_ocr):
    _put_config(client, "gemini", kind="token_api", default_prompt="default prompt")
    client.post(
        "/run",
        json={
            "backend": "gemini",
            "image_base64": "aGVsbG8=",
            "prompt": "custom latex instructions",
        },
    )
    assert fake_ocr.last_request.prompt == "custom latex instructions"


def test_run_defaults_to_scopes_first_enabled_backend(client):
    _put_config(client, "wmocr")
    _put_config(client, "gemini", kind="token_api")
    resp = client.post("/run", json={"image_url": "https://img.example/p.jpg"})
    # wmocr was created first, so it's the default when no backend is named.
    assert resp.json()["backend"] == "wmocr"


def test_run_unknown_backend_is_404(client):
    _put_config(client, "wmocr")
    resp = client.post(
        "/run", json={"image_url": "https://img.example/p.jpg", "backend": "nope"}
    )
    assert resp.status_code == 404


def test_run_without_any_config_is_404(client):
    resp = client.post("/run", json={"image_url": "https://img.example/p.jpg"})
    assert resp.status_code == 404


def test_run_maps_ocr_error_to_502(engine):
    class FailingClient:
        def recognize(self, request):
            raise OcrError("engine exploded")

    app = create_ocr_app(engine)
    app.dependency_overrides[get_client_builder] = lambda: (
        lambda config: FailingClient()
    )
    with TestClient(app) as c:
        _put_config(c, "wmocr")
        resp = c.post("/run", json={"image_url": "https://img.example/p.jpg"})
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

    monkeypatch.setattr("ocrapi.client.requests.get", fake_get)
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
    assert captured["url"] == "https://ocr.wiki.lan/api"
    assert ("image", "https://img.example/p.jpg") in captured["params"]
    assert ("engine", "tesseract") in captured["params"]
    assert ("langs[]", "en") in captured["params"]
    assert ("langs[]", "de") in captured["params"]
    assert ("crop[x]", "3") in captured["params"]
    assert ("crop[y]", "101") in captured["params"]
    assert ("crop[width]", "649") in captured["params"]
    assert ("crop[height]", "168") in captured["params"]


def test_wikimedia_client_defaults_to_tesseract_when_engine_unset(monkeypatch):
    captured = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"text": "recognized"}

    def fake_get(url, params=None, **kwargs):
        captured["params"] = params
        return Resp()

    monkeypatch.setattr("ocrapi.client.requests.get", fake_get)
    WikimediaOcrClient("https://ocr.wiki.lan").recognize(
        OcrRequest(image_url="https://img.example/p.jpg")
    )
    assert ("engine", "tesseract") in captured["params"]


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

    monkeypatch.setattr("ocrapi.client.requests.get", lambda *a, **k: Resp())
    client = WikimediaOcrClient("https://ocr.wiki.lan")
    with pytest.raises(OcrError, match="no engine"):
        client.recognize(OcrRequest(image_url="https://img.example/p.jpg"))
