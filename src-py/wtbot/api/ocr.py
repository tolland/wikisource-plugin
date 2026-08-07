import base64

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from ocrapi import catalog, service
from ocrapi.api import (
    OcrBackendList,
    OcrCatalogOut,
    OcrRunOut,
    backend_out,
    catalog_out,
)
from ocrapi.client import OcrCrop, OcrError, OcrRequest, build_client
from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.vfs.nodes import PageLeaf, resolve
from wtbot.vfs.store import PageStore

"""The wiki-aware sliver on top of the standalone ocrapi package: resolves
a wikisource:// page path to what ocrapi actually needs — a scope (the
site's family/code, so each wiki's backends are configured independently)
and a backend-reachable image URL (PageMeta's wiki-side rendition, never
the plugin's localhost one). Everything else — backend config, the actual
recognition call — is ocrapi.service; this module owns no OCR logic of its
own, only page/site resolution.

Backend *configuration* (PUT/DELETE/listing for editing, including
has_api_token / preserve-token-on-omit semantics) is not duplicated here:
configure a site's backends directly against the standalone app mounted at
/ocr, with scope=<family>/<code> (see wtbot.main.create_app and
viewer/src/lib/api.ts, which does exactly that). This module only reads,
for the plugin's own box-menu discovery.
"""

router = APIRouter(
    prefix="/pages/ocr", tags=["page-ocr"], route_class=DebugLoggingRoute
)


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


class OcrRunIn(BaseModel):
    path: str
    backend: str | None = None  # config name; default = site's first enabled
    annotation_id: str | None = None  # provenance only
    box: OcrBox | None = None  # crop for URL-driven backends; provenance otherwise
    image_base64: str | None = None  # cropped segment, for byte backends
    engine: str | None = None
    langs: list[str] | None = None
    prompt: str | None = None
    rotate: int = 0  # degrees clockwise, applied by the backend after the crop


def _scope_for(family: str, code: str) -> str:
    return f"{family}/{code}"


def _page_for(session: Session, path: str) -> PageLeaf:
    node = resolve(PageStore(session), path)
    if not isinstance(node, PageLeaf):
        raise HTTPException(status_code=404, detail=f"not a proofread page: {path}")
    return node


@router.get("/backends")
def list_backends(
    path: str = Query(..., description="wikisource:// VFS path of the Page: leaf"),
    session: Session = Depends(get_session),
) -> OcrBackendList:
    leaf = _page_for(session, path)
    scope = _scope_for(leaf.site.family, leaf.site.code)
    rows = service.list_backends(session, scope)
    return OcrBackendList(backends=[backend_out(row) for row in rows])


@router.get("/models")
def list_models(
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


@router.post("/run")
def run_ocr(
    body: OcrRunIn,
    session: Session = Depends(get_session),
    builder: service.ClientBuilder = Depends(get_client_builder),
) -> OcrRunOut:
    leaf = _page_for(session, body.path)
    scope = _scope_for(leaf.site.family, leaf.site.code)

    # Translate to the backend-reachable image URL: the wiki-side rendition
    # from PageMeta, never the sidecar's localhost /pages/image endpoint.
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

    return OcrRunOut(
        backend=config.name,
        kind=config.kind,
        engine=result.engine,
        text=result.text,
        text_base64=base64.b64encode(result.text.encode()).decode(),
    )
