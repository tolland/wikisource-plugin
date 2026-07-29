import base64
import os
from dataclasses import dataclass, field
from io import BytesIO
from typing import Protocol

import requests
from PIL import Image

from wtbot.model.ocr_backend import OcrBackendConfig, OcrBackendKind

"""The OCR-access seam: a typed request/result pair, a client Protocol, and
one client per backend kind.

``build_client`` turns a config row into a client — the extension point for
alternative backends: add a kind to OcrBackendKind, a client class here, and
a branch in build_client. Every client gets the full OcrRequest and uses the
parts its wire protocol supports (Wikimedia OCR only follows URLs; a token
vision API only takes bytes + prompt). Failures raise OcrError with a
human-readable message — the API layer maps that to a clean HTTP error
instead of a stack trace.
"""


class OcrError(Exception):
    """An OCR backend call failed in a way the user should see."""


@dataclass(slots=True)
class OcrCrop:
    """The region to recognize, in pixels of the image behind
    ``OcrRequest.image_url`` — the caller's coordinate space carries over
    unscaled, since it annotates that same rendition."""

    x: int
    y: int
    width: int
    height: int


@dataclass(slots=True)
class OcrRequest:
    """One recognition request, already resolved to backend-usable terms.

    ``image_url`` must be reachable *from the backend*, not just the
    caller — callers behind a proxy/localhost must resolve their own
    reachable URL before building this. ``crop`` narrows it to a region for
    backends that crop server-side (Wikimedia OCR). ``image_base64`` is an
    already-cropped segment, for backends that accept bytes instead of a
    URL. At least one of ``image_url``/``image_base64`` must be set; a
    client raises OcrError when the part it needs is missing.
    """

    image_url: str | None = None
    crop: OcrCrop | None = None
    image_base64: str | None = None
    engine: str | None = None
    langs: list[str] = field(default_factory=list)
    prompt: str | None = None


@dataclass(slots=True)
class OcrResult:
    text: str
    engine: str | None = None


class OcrClient(Protocol):
    def recognize(self, request: OcrRequest) -> OcrResult: ...


def _verify() -> bool | str:
    """CA bundle for a self-signed LAN backend. Independent of wtbot's
    WikiSettings on purpose — this package must not need wiki config to
    run standalone. OCRAPI_CA_BUNDLE points at a PEM file; unset verifies
    normally."""
    return os.environ.get("OCRAPI_CA_BUNDLE") or True


class WikimediaOcrClient:
    """The Wikimedia OCR HTTP API (https://ocr.wmcloud.org/api/doc), or a
    self-hosted instance of it. URL-driven: the service fetches the image
    itself, so the request must carry a URL the service can reach."""

    def __init__(self, base_url: str, timeout: float = 60.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def recognize(self, request: OcrRequest) -> OcrResult:
        if not request.image_url:
            raise OcrError(
                "Wikimedia OCR needs a backend-reachable image URL "
                "and none was given"
            )
        params: list[tuple[str, str]] = [("image", request.image_url)]
        # Tesseract is free/local; Wikimedia OCR's other engines (e.g.
        # Google) bill per call, so an unset engine must never default to
        # one of those silently.
        params.append(("engine", request.engine or "tesseract"))
        for lang in request.langs:
            params.append(("langs[]", lang))
        if request.crop is not None:
            params += [
                ("crop[x]", str(request.crop.x)),
                ("crop[y]", str(request.crop.y)),
                ("crop[width]", str(request.crop.width)),
                ("crop[height]", str(request.crop.height)),
            ]
        try:
            resp = requests.get(
                f"{self._base_url}/api",
                params=params,
                timeout=self._timeout,
                verify=_verify(),
                headers={"User-Agent": "ocrapi (wikisource-plugin)"},
            )
            resp.raise_for_status()
            payload = resp.json()
        except OcrError:
            raise
        except Exception as exc:  # noqa: BLE001 - surface as OcrError
            raise OcrError(f"Wikimedia OCR request failed: {exc}") from exc
        if "error" in payload:
            raise OcrError(f"Wikimedia OCR error: {payload['error']}")
        text = payload.get("text")
        if text is None:
            raise OcrError(f"Wikimedia OCR returned no text field: {payload}")
        return OcrResult(text=text, engine=payload.get("engine", request.engine))


class TokenApiOcrClient:
    """A generic bearer-token JSON vision API: POST base_url with
    {image_base64, prompt, langs}, expect {text}. The minimal contract a
    Gemini-style adapter (or any custom OCR service) can sit behind —
    the segment bytes and the optional custom prompt travel as-is."""

    def __init__(
        self,
        base_url: str,
        api_token: str | None,
        default_prompt: str | None = None,
        timeout: float = 120.0,
    ):
        self._base_url = base_url
        self._api_token = api_token
        self._default_prompt = default_prompt
        self._timeout = timeout

    def recognize(self, request: OcrRequest) -> OcrResult:
        if not request.image_base64:
            raise OcrError("this OCR backend needs the image segment bytes")
        headers = {"User-Agent": "ocrapi (wikisource-plugin)"}
        if self._api_token:
            headers["Authorization"] = f"Bearer {self._api_token}"
        body = {
            "image_base64": request.image_base64,
            "prompt": request.prompt or self._default_prompt,
            "langs": request.langs,
        }
        try:
            resp = requests.post(
                self._base_url,
                json=body,
                timeout=self._timeout,
                verify=_verify(),
                headers=headers,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:  # noqa: BLE001 - surface as OcrError
            raise OcrError(f"OCR request failed: {exc}") from exc
        text = payload.get("text")
        if text is None:
            raise OcrError(f"OCR backend returned no text field: {payload}")
        return OcrResult(text=text, engine=payload.get("engine"))


def _image_bytes_for_upload(request: OcrRequest, *, verify: bool | str) -> bytes:
    """Resolves an [OcrRequest] to raw image bytes for a multipart upload,
    for backends (pix2tex) that take neither a URL nor server-side
    cropping: ``image_base64`` is used as-is (already cropped, by
    convention), otherwise ``image_url`` is fetched and, if ``crop`` is
    set, cropped locally with Pillow before re-encoding to PNG."""
    if request.image_base64:
        return base64.b64decode(request.image_base64)
    if not request.image_url:
        raise OcrError("this OCR backend needs an image URL or the segment bytes")
    try:
        resp = requests.get(request.image_url, timeout=30, verify=verify)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - surface as OcrError
        raise OcrError(f"could not fetch {request.image_url}: {exc}") from exc
    if request.crop is None:
        return resp.content
    try:
        image = Image.open(BytesIO(resp.content))
        box = (
            request.crop.x,
            request.crop.y,
            request.crop.x + request.crop.width,
            request.crop.y + request.crop.height,
        )
        cropped = image.crop(box)
        out = BytesIO()
        cropped.save(out, format="PNG")
        return out.getvalue()
    except OcrError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface as OcrError
        raise OcrError(f"could not crop the fetched image: {exc}") from exc


class Pix2TexClient:
    """A self-hosted pix2tex/LaTeX-OCR instance (the
    ``lukasblecher/pix2tex:api`` Docker image) — free, local, specialized
    on mathematical notation rather than general text. Multipart file
    upload only: no URL-fetch or crop support server-side, so this client
    resolves the image itself (see [_image_bytes_for_upload]) and always
    uploads bytes. No prompt: the model isn't instructable."""

    def __init__(self, base_url: str, timeout: float = 120.0):
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def recognize(self, request: OcrRequest) -> OcrResult:
        image_bytes = _image_bytes_for_upload(request, verify=_verify())
        try:
            resp = requests.post(
                f"{self._base_url}/bytes/",
                files={"file": ("segment.png", image_bytes, "image/png")},
                timeout=self._timeout,
                verify=_verify(),
                headers={"User-Agent": "ocrapi (wikisource-plugin)"},
            )
            resp.raise_for_status()
            text = resp.json()
        except Exception as exc:  # noqa: BLE001 - surface as OcrError
            raise OcrError(f"pix2tex request failed: {exc}") from exc
        if not isinstance(text, str):
            raise OcrError(f"pix2tex returned an unexpected response: {text!r}")
        return OcrResult(text=text, engine="pix2tex")


class FakeOcrClient:
    """In-memory client for tests: canned text, records the last request."""

    def __init__(self, text: str = "fake ocr text", engine: str | None = "fake"):
        self.text = text
        self.engine = engine
        self.last_request: OcrRequest | None = None

    def recognize(self, request: OcrRequest) -> OcrResult:
        self.last_request = request
        return OcrResult(text=self.text, engine=self.engine)


def build_client(config: OcrBackendConfig) -> OcrClient:
    """Config → client. THE place to register alternative backends."""
    match config.kind:
        case OcrBackendKind.wikimedia:
            return WikimediaOcrClient(config.base_url)
        case OcrBackendKind.token_api:
            return TokenApiOcrClient(
                config.base_url, config.api_token, config.default_prompt
            )
        case OcrBackendKind.pix2tex:
            return Pix2TexClient(config.base_url)
    raise OcrError(f"unknown OCR backend kind: {config.kind}")
