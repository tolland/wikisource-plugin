import pytest

from ocrapi import catalog
from wtbot.model.ocr_backend import OcrBackendConfig, OcrBackendKind

"""Tests for engine/model discovery -- the thing that turns py-ocrapi's
raw ``/api/models`` dump (hundreds of languages per engine, ~200KB for
Google Vision alone) into something a caller can cache and filter down to
a handful of menu entries.

Two behaviours matter beyond the happy path: the per-engine
``available_langs`` narrowing must degrade to the declared list rather than
fail (an over-broad menu beats no menu), and the whole thing must be cached
-- discovery is on the path of opening an editor, and this list changes
only when the service is redeployed.
"""


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture
def wikimedia_config() -> OcrBackendConfig:
    return OcrBackendConfig(
        scope="wikisource/en",
        name="wmocr",
        kind=OcrBackendKind.wikimedia,
        base_url="https://ocr.example",
    )


def test_fetch_catalog_prefers_installed_models_over_declared(monkeypatch):
    def fake_get(url, params=None, **kwargs):
        if url.endswith("/api/models"):
            return FakeResponse(
                {
                    "tesseract": {"en": "English", "de": "German", "fr": "French"},
                    "pix2tex": {},
                }
            )
        assert url.endswith("/api/available_langs")
        if params["engine"] == "tesseract":
            # Only English is actually installed, even though models.json
            # declares three.
            return FakeResponse({"available_langs": {"en": "English"}})
        return FakeResponse({"available_langs": {}})

    monkeypatch.setattr("ocrapi.catalog.requests.get", fake_get)
    engines = catalog.fetch_catalog("https://ocr.example/")
    assert [e.engine for e in engines] == ["tesseract", "pix2tex"]
    assert engines[0].models == [catalog.OcrModel(code="en", title="English")]
    assert engines[1].models == []


def test_fetch_catalog_falls_back_to_declared_models(monkeypatch):
    def fake_get(url, params=None, **kwargs):
        if url.endswith("/api/models"):
            return FakeResponse({"tesseract": {"en": "English", "de": "German"}})
        raise RuntimeError("available_langs is not implemented here")

    monkeypatch.setattr("ocrapi.catalog.requests.get", fake_get)
    [tesseract] = catalog.fetch_catalog("https://ocr.example")
    assert [m.code for m in tesseract.models] == ["de", "en"]  # sorted by code


def test_catalog_for_caches_by_base_url(wikimedia_config):
    calls = []

    def fetcher(base_url):
        calls.append(base_url)
        return [catalog.OcrEngineModels(engine="tesseract")]

    cache = catalog.CatalogCache()
    for _ in range(3):
        found = catalog.catalog_for(wikimedia_config, fetcher=fetcher, cache=cache)
        assert found.error is None
        assert [e.engine for e in found.engines] == ["tesseract"]
    assert calls == ["https://ocr.example"]

    catalog.catalog_for(wikimedia_config, fetcher=fetcher, cache=cache, refresh=True)
    assert len(calls) == 2


def test_catalog_for_expires_entries(wikimedia_config):
    calls = []

    def fetcher(base_url):
        calls.append(base_url)
        return []

    cache = catalog.CatalogCache(ttl_seconds=0)
    catalog.catalog_for(wikimedia_config, fetcher=fetcher, cache=cache)
    catalog.catalog_for(wikimedia_config, fetcher=fetcher, cache=cache)
    assert len(calls) == 2


def test_catalog_for_reports_the_failure_instead_of_raising(wikimedia_config):
    def boom(base_url):
        raise RuntimeError("connection refused")

    found = catalog.catalog_for(
        wikimedia_config, fetcher=boom, cache=catalog.CatalogCache()
    )
    assert found.engines == []
    assert "connection refused" in found.error


def test_catalog_for_skips_backends_without_a_discovery_api():
    config = OcrBackendConfig(
        scope="wikisource/en",
        name="gemini",
        kind=OcrBackendKind.token_api,
        base_url="https://vision.example/ocr",
    )

    def fetcher(base_url):
        raise AssertionError("token_api backends must not be introspected")

    found = catalog.catalog_for(config, fetcher=fetcher, cache=catalog.CatalogCache())
    assert found == catalog.OcrCatalog(backend="gemini")


def test_a_failed_fetch_is_not_cached(wikimedia_config):
    calls = []

    def flaky(base_url):
        calls.append(base_url)
        if len(calls) == 1:
            raise RuntimeError("connection refused")
        return [catalog.OcrEngineModels(engine="tesseract")]

    cache = catalog.CatalogCache()
    assert catalog.catalog_for(wikimedia_config, fetcher=flaky, cache=cache).error
    recovered = catalog.catalog_for(wikimedia_config, fetcher=flaky, cache=cache)
    assert recovered.error is None
