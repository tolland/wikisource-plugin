import base64

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlmodel import Session

from ocrapi import catalog, service
from ocrapi.client import OcrCrop, OcrError, OcrRequest, OcrResult, build_client
from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.model.ocr_backend import DEFAULT_SCOPE, OcrBackendConfig, OcrBackendKind
from wtbot.vfs.nodes import PageLeaf, resolve
from wtbot.vfs.store import PageStore

"""OCR configuration, discovery, and recognition routes.

The generic ``/ocr`` routes accept an explicit scope and image. The
``/pages/ocr`` routes add the wiki-aware translation from a wikisource://
page path to a site scope and backend-reachable image URL. Both are part of
wtbot's main API; ``ocrapi`` contains only the reusable service and HTTP
client code used behind these routes.
"""

router = APIRouter(tags=["ocr"], route_class=DebugLoggingRoute)


def get_client_builder() -> service.ClientBuilder:
    """Dependency seam: tests override this to inject a FakeOcrClient."""
    return build_client


def get_catalog_fetcher() -> catalog.CatalogFetcher:
    """Dependency seam for engine/model discovery (see ocrapi.catalog)."""
    return catalog.fetch_catalog


class OcrBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class PageOcrRunIn(BaseModel):
    path: str
    backend: str | None = None  # config name; default = site's first enabled
    annotation_id: str | None = None  # provenance only
    box: OcrBox | None = None  # crop for URL-driven backends; provenance otherwise
    image_base64: str | None = None  # cropped segment, for byte backends
    engine: str | None = None
    langs: list[str] | None = None
    prompt: str | None = None
    rotate: int = 0  # degrees clockwise, applied by the backend after the crop


class OcrBackendOut(BaseModel):
    name: str
    kind: OcrBackendKind
    base_url: str
    default_engine: str | None
    default_langs: list[str]
    default_prompt: str | None
    enabled: bool
    has_api_token: bool
    supports_prompt: bool
    supports_segment: bool
    supports_discovery: bool


class OcrBackendList(BaseModel):
    backends: list[OcrBackendOut]


class OcrModelOut(BaseModel):
    code: str
    title: str


class OcrEngineOut(BaseModel):
    engine: str
    models: list[OcrModelOut]


class OcrCatalogOut(BaseModel):
    backend: str
    engines: list[OcrEngineOut]
    error: str | None = None


class OcrBackendUpsert(BaseModel):
    kind: OcrBackendKind
    base_url: str
    api_token: str | None = None
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
    backend: str | None = None
    image_url: str | None = None
    image_base64: str | None = None
    crop: OcrCropIn | None = None
    engine: str | None = None
    langs: list[str] | None = None
    prompt: str | None = None
    rotate: int = 0

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
    text_base64: str


_SEGMENT_KINDS = {OcrBackendKind.token_api}
_PROMPT_KINDS = {OcrBackendKind.token_api}
_DISCOVERABLE_KINDS = {OcrBackendKind.wikimedia}


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
        supports_discovery=row.kind in _DISCOVERABLE_KINDS,
    )


def catalog_out(found: catalog.OcrCatalog) -> OcrCatalogOut:
    return OcrCatalogOut(
        backend=found.backend,
        engines=[
            OcrEngineOut(
                engine=engine.engine,
                models=[OcrModelOut(code=m.code, title=m.title) for m in engine.models],
            )
            for engine in found.engines
        ],
        error=found.error,
    )


@router.get("/ocr/backends")
def list_configured_backends(
    scope: str = Query(DEFAULT_SCOPE),
    enabled_only: bool = Query(True),
    session: Session = Depends(get_session),
) -> OcrBackendList:
    rows = service.list_backends(session, scope, enabled_only=enabled_only)
    return OcrBackendList(backends=[backend_out(row) for row in rows])


@router.get("/ocr/models")
def list_configured_models(
    scope: str = Query(DEFAULT_SCOPE),
    backend: str | None = Query(
        None, description="config name; default = scope's first enabled backend"
    ),
    refresh: bool = Query(False, description="bypass the TTL cache"),
    session: Session = Depends(get_session),
    fetcher: catalog.CatalogFetcher = Depends(get_catalog_fetcher),
) -> OcrCatalogOut:
    try:
        config = service.resolve_backend(session, scope, backend)
    except service.UnknownBackend as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return catalog_out(catalog.catalog_for(config, fetcher=fetcher, refresh=refresh))


@router.put("/ocr/config/{name}")
def upsert_config(
    name: str,
    body: OcrBackendUpsert,
    scope: str = Query(DEFAULT_SCOPE),
    session: Session = Depends(get_session),
) -> OcrBackendOut:
    row = service.upsert_backend(
        session,
        scope,
        name,
        kind=body.kind,
        base_url=body.base_url,
        api_token=(
            body.api_token if "api_token" in body.model_fields_set else service.UNSET
        ),
        default_engine=body.default_engine,
        default_langs=body.default_langs,
        default_prompt=body.default_prompt,
        enabled=body.enabled,
    )
    return backend_out(row)


@router.delete("/ocr/config/{name}", status_code=204)
def delete_config(
    name: str,
    scope: str = Query(DEFAULT_SCOPE),
    session: Session = Depends(get_session),
) -> None:
    if not service.delete_backend(session, scope, name):
        raise HTTPException(status_code=404, detail=f"no OCR backend {name}")


@router.post("/ocr/run")
def run_generic_ocr(
    body: OcrRunIn,
    session: Session = Depends(get_session),
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
        rotate=body.rotate,
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
    return _run_out(config, result)


def _scope_for(family: str, code: str) -> str:
    return f"{family}/{code}"


def _page_for(session: Session, path: str) -> PageLeaf:
    node = resolve(PageStore(session), path)
    if not isinstance(node, PageLeaf):
        raise HTTPException(status_code=404, detail=f"not a proofread page: {path}")
    return node


@router.get("/pages/ocr/backends", tags=["page-ocr"])
def list_page_backends(
    path: str = Query(..., description="wikisource:// VFS path of the Page: leaf"),
    session: Session = Depends(get_session),
) -> OcrBackendList:
    leaf = _page_for(session, path)
    scope = _scope_for(leaf.site.family, leaf.site.code)
    rows = service.list_backends(session, scope)
    return OcrBackendList(backends=[backend_out(row) for row in rows])


@router.get("/pages/ocr/models", tags=["page-ocr"])
def list_page_models(
    path: str = Query(..., description="wikisource:// VFS path of the Page: leaf"),
    backend: str | None = Query(
        None, description="config name; default = site's first enabled backend"
    ),
    refresh: bool = Query(False, description="bypass the TTL cache"),
    session: Session = Depends(get_session),
    fetcher: catalog.CatalogFetcher = Depends(get_catalog_fetcher),
) -> OcrCatalogOut:
    """The engines/languages available for this page's site — what the
    plugin's "Run OCR" menu is built from. The full list is far too long to
    put in a menu directly (Google Vision alone declares hundreds of
    languages); the plugin narrows it to a per-project favourites list and
    this endpoint is what populates the picker behind that setting."""
    leaf = _page_for(session, path)
    scope = _scope_for(leaf.site.family, leaf.site.code)
    try:
        config = service.resolve_backend(session, scope, backend)
    except service.UnknownBackend as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return catalog_out(catalog.catalog_for(config, fetcher=fetcher, refresh=refresh))


@router.post("/pages/ocr/run", tags=["page-ocr"])
def run_page_ocr(
    body: PageOcrRunIn,
    session: Session = Depends(get_session),
    builder: service.ClientBuilder = Depends(get_client_builder),
) -> OcrRunOut:
    leaf = _page_for(session, body.path)
    scope = _scope_for(leaf.site.family, leaf.site.code)

    # Translate to the backend-reachable image URL: the wiki-side rendition
    # from PageMeta, never the sidecar's localhost image endpoint.
    meta = PageStore(session).page_meta(leaf.page)
    image_url = (meta.source_image_url or meta.thumb_url) if meta is not None else None

    crop = None
    if body.box is not None:
        crop = OcrCrop(
            x=round(body.box.x),
            y=round(body.box.y),
            width=max(1, round(body.box.width)),
            height=max(1, round(body.box.height)),
        )

    request = OcrRequest(
        image_url=image_url,
        crop=crop,
        image_base64=body.image_base64,
        engine=body.engine,
        langs=body.langs or [],
        prompt=body.prompt,
        rotate=body.rotate,
    )
    try:
        config, result = service.recognize(
            session, scope, request, backend_name=body.backend, client_builder=builder
        )
    except service.UnknownBackend as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OcrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return _run_out(config, result)


def _run_out(config: OcrBackendConfig, result: OcrResult) -> OcrRunOut:
    return OcrRunOut(
        backend=config.name,
        kind=config.kind,
        engine=result.engine,
        text=result.text,
        text_base64=base64.b64encode(result.text.encode()).decode(),
    )
