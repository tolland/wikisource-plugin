import logging
import os
import time
from dataclasses import dataclass, field
from typing import Protocol

import requests

from wtbot.model.ocr_backend import OcrBackendConfig, OcrBackendKind

"""Engine/model discovery: what a configured backend can actually be asked
to do, so a caller can build a menu instead of hardcoding engine names.

The wire source is py-ocrapi (https://github.com/tolland/py-ocrapi, the
Python port of Wikimedia OCR) which serves two endpoints:

- ``GET /api/models`` -> ``{engine: {code: title}}`` for every engine it
  knows, from its bundled ``models.json``
- ``GET /api/available_langs?engine=X`` -> the subset actually installed
  for that engine (tesseract only ships the traineddata it was built with;
  ``models.json`` lists far more)

We prefer ``available_langs`` per engine and fall back to the ``models``
entry when that call fails, so a menu never offers a language the backend
would reject. The result is cached per base URL: ``/api/models`` alone is
~200KB of language names for Google Vision, it changes only when the
service is redeployed, and the whole point of this module is to keep that
list off the UI's hot path.
"""

logger = logging.getLogger(__name__)

CATALOG_TTL_SECONDS = 3600.0


@dataclass(frozen=True, slots=True)
class OcrModel:
    """One recognizable language/model, e.g. ``en`` / "English"."""

    code: str
    title: str


@dataclass(frozen=True, slots=True)
class OcrEngineModels:
    """One engine and the models it offers. An empty [models] is normal,
    not an error — pix2tex recognizes mathematical notation and has no
    language dimension at all."""

    engine: str
    models: list[OcrModel] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class OcrCatalog:
    """What one configured backend offers. [error] is set when discovery
    failed: callers render the (empty) catalog plus the message rather
    than failing the whole menu — a backend that can't be introspected can
    still be run with its configured defaults."""

    backend: str
    engines: list[OcrEngineModels] = field(default_factory=list)
    error: str | None = None


class CatalogFetcher(Protocol):
    def __call__(self, base_url: str) -> list[OcrEngineModels]: ...


def _verify() -> bool | str:
    """Same CA-bundle seam as ocrapi.client._verify — discovery hits the
    same self-signed LAN host the recognition calls do."""
    return os.environ.get("OCRAPI_CA_BUNDLE") or True


def fetch_catalog(base_url: str, timeout: float = 30.0) -> list[OcrEngineModels]:
    """Live discovery against a py-ocrapi/Wikimedia OCR instance. Raises
    ``requests``/``ValueError`` on failure; [catalog_for] maps that to
    OcrCatalog.error."""
    root = base_url.rstrip("/")
    headers = {"User-Agent": "ocrapi (wikisource-plugin)"}
    resp = requests.get(
        f"{root}/api/models", timeout=timeout, verify=_verify(), headers=headers
    )
    resp.raise_for_status()
    declared: dict[str, dict[str, str]] = resp.json()

    engines: list[OcrEngineModels] = []
    for engine, models in declared.items():
        engines.append(
            OcrEngineModels(
                engine=engine,
                models=_available_models(root, engine, models, timeout, headers),
            )
        )
    return engines


def _available_models(
    root: str,
    engine: str,
    declared: dict[str, str],
    timeout: float,
    headers: dict[str, str],
) -> list[OcrModel]:
    """The engine's installed models, falling back to what ``/api/models``
    declared. A failure here is not fatal: an over-broad list is a much
    smaller problem than no list at all."""
    try:
        resp = requests.get(
            f"{root}/api/available_langs",
            params={"engine": engine},
            timeout=timeout,
            verify=_verify(),
            headers=headers,
        )
        resp.raise_for_status()
        available: dict[str, str] = resp.json()["available_langs"]
    except Exception as exc:  # noqa: BLE001 - degrade to the declared list
        logger.info("available_langs failed for %s/%s: %s", root, engine, exc)
        available = declared
    return [
        OcrModel(code=code, title=title) for code, title in sorted(available.items())
    ]


class CatalogCache:
    """TTL cache keyed by base URL. Shared across scopes on purpose: two
    scopes pointed at the same service have the same catalog."""

    def __init__(self, ttl_seconds: float = CATALOG_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._entries: dict[str, tuple[float, list[OcrEngineModels]]] = {}

    def get(
        self, base_url: str, fetcher: CatalogFetcher, *, refresh: bool = False
    ) -> list[OcrEngineModels]:
        now = time.monotonic()
        cached = self._entries.get(base_url)
        if not refresh and cached is not None and now - cached[0] < self._ttl:
            return cached[1]
        engines = fetcher(base_url)
        self._entries[base_url] = (now, engines)
        return engines

    def clear(self) -> None:
        self._entries.clear()


CACHE = CatalogCache()
"""Process-wide cache. Tests clear it; nothing else should need to."""


def catalog_for(
    config: OcrBackendConfig,
    *,
    fetcher: CatalogFetcher = fetch_catalog,
    cache: CatalogCache = CACHE,
    refresh: bool = False,
) -> OcrCatalog:
    """[config]'s engines/models, cached. Only URL-driven backends expose a
    discovery API; a token_api backend is a single opaque model, so it gets
    an empty catalog rather than a failed call."""
    if config.kind is not OcrBackendKind.wikimedia:
        return OcrCatalog(backend=config.name)
    try:
        engines = cache.get(config.base_url, fetcher, refresh=refresh)
    except Exception as exc:  # noqa: BLE001 - surfaced as OcrCatalog.error
        logger.warning("OCR catalog discovery failed for %s: %s", config.base_url, exc)
        return OcrCatalog(backend=config.name, error=f"discovery failed: {exc}")
    return OcrCatalog(backend=config.name, engines=engines)
