import base64

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlmodel import Session

from ocrapi import service
from ocrapi.client import OcrCrop, OcrError, OcrRequest, build_client
from ocrapi.deps import get_ocr_session
from wtbot.model.ocr_backend import DEFAULT_SCOPE, OcrBackendConfig, OcrBackendKind

"""Generic OCR HTTP surface — no wiki/page concepts, no credentials beyond
a per-backend API token. A caller identifies what to OCR with a plain
``image_url`` (must be reachable *from wherever this app runs*) or
``image_base64``, and optionally a ``scope`` to pick among several
configured backends (wtbot's page-scoped wrapper at ``/pages/ocr`` passes
a wiki's family/code as scope; most standalone callers can ignore it and
use the default scope).
"""

router = APIRouter(tags=["ocr"])


def get_client_builder() -> service.ClientBuilder:
    """Dependency seam: tests override this to inject a FakeOcrClient
    instead of hitting a real backend over HTTP."""
    return build_client


class OcrBackendOut(BaseModel):
    name: str
    kind: OcrBackendKind
    base_url: str
    default_engine: str | None
    default_langs: list[str]
    default_prompt: str | None
    enabled: bool
    has_api_token: bool
    # Capability flags so a caller can shape its UI without knowing kinds.
    supports_prompt: bool
    supports_segment: bool


class OcrBackendList(BaseModel):
    backends: list[OcrBackendOut]


class OcrBackendUpsert(BaseModel):
    kind: OcrBackendKind
    base_url: str
    api_token: str | None = None
    # "tesseract" is Wikimedia OCR's free/local engine, so a config that
    # doesn't say otherwise defaults there rather than to a paid engine.
    default_engine: str | None = "tesseract"
    default_langs: list[str] = []
    default_prompt: str | None = None
    enabled: bool = True


class OcrCropIn(BaseModel):
    x: float
    y: float
    width: float
    height: float


class OcrRunIn(BaseModel):
    scope: str = DEFAULT_SCOPE
    backend: str | None = None  # config name; default = scope's first enabled
    image_url: str | None = None
    image_base64: str | None = None
    crop: OcrCropIn | None = None  # only meaningful with image_url
    engine: str | None = None
    langs: list[str] | None = None
    prompt: str | None = None

    @model_validator(mode="after")
    def _need_an_image(self) -> "OcrRunIn":
        if not self.image_url and not self.image_base64:
            raise ValueError("need image_url or image_base64")
        return self


class OcrRunOut(BaseModel):
    backend: str
    kind: OcrBackendKind
    engine: str | None
    text: str
    # base64 alongside plain text: some callers (the wikitext-plugin's
    # minimal JSON reader) don't unescape JSON string values, so multi-line
    # text needs an encoded form too.
    text_base64: str


# Per-kind capability flags: which OcrRequest fields a backend actually
# uses, so a caller can shape its UI (show a prompt box, crop client-side)
# without knowing kinds. wikimedia is URL+server-crop only; token_api and
# pix2tex both need bytes, but only token_api accepts a custom prompt.
_SEGMENT_KINDS = {OcrBackendKind.token_api, OcrBackendKind.pix2tex}
_PROMPT_KINDS = {OcrBackendKind.token_api}


def backend_out(row: OcrBackendConfig) -> OcrBackendOut:
    return OcrBackendOut(
        name=row.name,
        kind=row.kind,
        base_url=row.base_url,
        default_engine=row.default_engine,
        default_langs=row.langs_list(),
        default_prompt=row.default_prompt,
        enabled=row.enabled,
        has_api_token=bool(row.api_token),
        supports_prompt=row.kind in _PROMPT_KINDS,
        supports_segment=row.kind in _SEGMENT_KINDS,
    )


@router.get("/backends")
def list_backends(
    scope: str = Query(DEFAULT_SCOPE),
    # False for an admin/config UI that must show (and let you re-enable)
    # disabled backends too; the plugin's page-scoped discovery wants the
    # default (enabled only).
    enabled_only: bool = Query(True),
    session: Session = Depends(get_ocr_session),
) -> OcrBackendList:
    rows = service.list_backends(session, scope, enabled_only=enabled_only)
    return OcrBackendList(backends=[backend_out(row) for row in rows])


@router.put("/config/{name}")
def upsert_config(
    name: str,
    body: OcrBackendUpsert,
    scope: str = Query(DEFAULT_SCOPE),
    session: Session = Depends(get_ocr_session),
) -> OcrBackendOut:
    row = service.upsert_backend(
        session,
        scope,
        name,
        kind=body.kind,
        base_url=body.base_url,
        # An omitted token means "keep the stored secret"; explicit null
        # clears it -- lets an edit form leave its write-only token field
        # blank without clobbering what's saved.
        api_token=(
            body.api_token if "api_token" in body.model_fields_set else service.UNSET
        ),
        default_engine=body.default_engine,
        default_langs=body.default_langs,
        default_prompt=body.default_prompt,
        enabled=body.enabled,
    )
    return backend_out(row)


@router.delete("/config/{name}", status_code=204)
def delete_config(
    name: str,
    scope: str = Query(DEFAULT_SCOPE),
    session: Session = Depends(get_ocr_session),
) -> None:
    if not service.delete_backend(session, scope, name):
        raise HTTPException(status_code=404, detail=f"no OCR backend {name}")


@router.post("/run")
def run_ocr(
    body: OcrRunIn,
    session: Session = Depends(get_ocr_session),
    builder: service.ClientBuilder = Depends(get_client_builder),
) -> OcrRunOut:
    crop = (
        OcrCrop(
            x=round(body.crop.x),
            y=round(body.crop.y),
            width=max(1, round(body.crop.width)),
            height=max(1, round(body.crop.height)),
        )
        if body.crop is not None
        else None
    )
    request = OcrRequest(
        image_url=body.image_url,
        crop=crop,
        image_base64=body.image_base64,
        engine=body.engine,
        langs=body.langs or [],
        prompt=body.prompt,
    )
    try:
        config, result = service.recognize(
            session,
            body.scope,
            request,
            backend_name=body.backend,
            client_builder=builder,
        )
    except service.UnknownBackend as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OcrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return OcrRunOut(
        backend=config.name,
        kind=config.kind,
        engine=result.engine,
        text=result.text,
        text_base64=base64.b64encode(result.text.encode()).decode(),
    )
