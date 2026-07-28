from dataclasses import dataclass, field
from typing import Protocol

import requests

from wtbot.model.ocr_backend import OcrBackendConfig, OcrBackendKind
from wtbot.settings import WikiSettings

"""The OCR-access seam: a typed request/result pair, a client Protocol, and
one client per backend kind — mirroring the WikiClient seam in wtbot.wiki.

The API layer (wtbot.api.ocr) resolves *what* to OCR (the wiki-reachable
image URL for the page, the cropped segment bytes the editor sent) and
*which* backend (an OcrBackendConfig row); ``build_client`` turns the
config into a client. That function is the extension point for alternative
backends: add a kind to OcrBackendKind, a client class here, and a branch
in build_client — nothing in the API layer changes.

Every client gets the full OcrRequest and uses the parts its wire protocol
supports (Wikimedia OCR only follows URLs; a token vision API only takes
bytes + prompt). Failures raise OcrError with a human-readable message —
the API layer maps that to a clean HTTP error instead of a stack trace.
"""


class OcrError(Exception):
    """An OCR backend call failed in a way the user should see."""


@dataclass(slots=True)
class OcrCrop:
    """The bounding-box region to recognize, in pixels of the image behind
    ``OcrRequest.image_url`` — the same rendition the editor annotates, so
    box coordinates carry over unscaled."""

    x: int
    y: int
    width: int
    height: int


@dataclass(slots=True)
class OcrRequest:
    """One recognition request, already resolved to backend-usable terms.

    ``image_url`` is the *backend-reachable* URL of the page scan (the
    wiki-side URL from PageMeta, never the plugin's localhost rendition),
    with ``crop`` narrowing it to the bounding-box region for backends
    that crop server-side (Wikimedia OCR). ``image_base64`` is the
    already-cropped segment as the editor sees it, for backends that
    accept bytes. Any part may be None; a client raises OcrError when the
    part it needs is missing.
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
    """CA bundle for self-signed LAN backends — same knob the wiki side uses."""
    return WikiSettings.from_env().ca_bundle or True


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
                "and none is known for this page"
            )
        params: list[tuple[str, str]] = [("image", request.image_url)]
        if request.engine:
            params.append(("engine", request.engine))
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
                f"{self._base_url}/api.php",
                params=params,
                timeout=self._timeout,
                verify=_verify(),
                headers={"User-Agent": "wtbot (wikisource-plugin)"},
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
        headers = {"User-Agent": "wtbot (wikisource-plugin)"}
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
    raise OcrError(f"unknown OCR backend kind: {config.kind}")
