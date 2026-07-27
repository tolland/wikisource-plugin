import base64
from collections.abc import Callable
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from wtbot.api.debug_loggig_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.model import OcrBackendConfig, OcrBackendKind, Site
from wtbot.ocr import OcrClient, OcrError, OcrRequest, build_client
from wtbot.vfs.nodes import PageLeaf, resolve
from wtbot.vfs.store import PageStore

"""OCR over page-scan regions, proxied through the sidecar.

The plugin never talks to an OCR service directly: per-site backends are
configured here (/ocr/config, keyed by pywikibot family+code), the UI asks
/ocr/backends what a page's site offers, and /ocr/run performs one
recognition. The sidecar owns the two things the editor can't know:

- URL translation: the editor's image is a localhost rendition served by
  this sidecar; OCR services need the *wiki-side* URL (PageMeta's
  source_image_url), which is what /ocr/run passes along for URL-driven
  backends like Wikimedia OCR.
- backend credentials/CA: tokens and the LAN CA bundle stay server-side.

Segment-driven backends (kind=token_api) instead receive the cropped
bounding-box bytes the editor sends (image_base64) plus an optional custom
prompt — e.g. LaTeX instructions for idiosyncratic 19th-century
typesetting — with the config's default_prompt as fallback.

The result is returned to the caller, not written anywhere: previewing and
applying OCR text into a text range is the editor's workflow.
"""

router = APIRouter(prefix="/ocr", tags=["ocr"], route_class=DebugLoggingRoute)

ClientBuilder = Callable[[OcrBackendConfig], OcrClient]


def get_client_builder() -> ClientBuilder:
    """Dependency seam: tests override this to inject a FakeOcrClient."""
    return build_client


class OcrBackendOut(BaseModel):
    name: str
    kind: OcrBackendKind
    base_url: str
    default_engine: str | None
    default_langs: list[str]
    default_prompt: str | None
    enabled: bool
    # Capability flags so the UI can shape its menu without knowing kinds.
    supports_prompt: bool
    supports_segment: bool


class OcrBackendList(BaseModel):
    backends: list[OcrBackendOut]


class OcrBackendUpsert(BaseModel):
    kind: OcrBackendKind
    base_url: str
    api_token: str | None = None
    default_engine: str | None = None
    default_langs: list[str] = []
    default_prompt: str | None = None
    enabled: bool = True


class OcrBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class OcrRunIn(BaseModel):
    path: str
    backend: str | None = None  # config name; default = first enabled
    annotation_id: str | None = None  # provenance only
    box: OcrBox | None = None  # provenance only (the crop already happened)
    image_base64: str | None = None  # cropped segment, for byte backends
    engine: str | None = None
    langs: list[str] | None = None
    prompt: str | None = None


class OcrRunOut(BaseModel):
    backend: str
    kind: OcrBackendKind
    engine: str | None
    text: str
    # The same text base64-encoded: the plugin's minimal JSON reader does
    # not unescape string values, so multi-line text travels encoded (the
    # same convention as /preview/render's html_base64).
    text_base64: str


def _backend_out(row: OcrBackendConfig) -> OcrBackendOut:
    segment = row.kind is OcrBackendKind.token_api
    return OcrBackendOut(
        name=row.name,
        kind=row.kind,
        base_url=row.base_url,
        default_engine=row.default_engine,
        default_langs=row.langs_list(),
        default_prompt=row.default_prompt,
        enabled=row.enabled,
        supports_prompt=segment,
        supports_segment=segment,
    )


def _site_for(session: Session, family: str, code: str) -> Site:
    site = session.exec(
        select(Site).where(Site.family == family, Site.code == code)
    ).first()
    if site is None:
        raise HTTPException(status_code=404, detail=f"no site {family}/{code}")
    return site


def _page_for(session: Session, path: str) -> PageLeaf:
    node = resolve(PageStore(session), path)
    if not isinstance(node, PageLeaf):
        raise HTTPException(status_code=404, detail=f"not a proofread page: {path}")
    return node


def _configs_for_site(session: Session, site_pk: int) -> list[OcrBackendConfig]:
    return list(
        session.exec(
            select(OcrBackendConfig)
            .where(OcrBackendConfig.site_pk == site_pk)
            .order_by(OcrBackendConfig.pk)
        ).all()
    )


# ---- backend discovery (UI-facing, by page path) ------------------------------


@router.get("/backends")
def list_backends(
    path: str = Query(..., description="wikisource:// VFS path of the Page: leaf"),
    session: Session = Depends(get_session),
) -> OcrBackendList:
    leaf = _page_for(session, path)
    rows = [c for c in _configs_for_site(session, leaf.site.pk) if c.enabled]
    return OcrBackendList(backends=[_backend_out(row) for row in rows])


# ---- config CRUD (admin/debug-facing, by site) --------------------------------


@router.get("/config")
def list_config(
    family: str = Query(...),
    code: str = Query(...),
    session: Session = Depends(get_session),
) -> OcrBackendList:
    site = _site_for(session, family, code)
    return OcrBackendList(
        backends=[_backend_out(row) for row in _configs_for_site(session, site.pk)]
    )


@router.put("/config/{name}")
def upsert_config(
    name: str,
    body: OcrBackendUpsert,
    family: str = Query(...),
    code: str = Query(...),
    session: Session = Depends(get_session),
) -> OcrBackendOut:
    site = _site_for(session, family, code)
    row = session.exec(
        select(OcrBackendConfig).where(
            OcrBackendConfig.site_pk == site.pk, OcrBackendConfig.name == name
        )
    ).first()
    if row is None:
        row = OcrBackendConfig(
            site_pk=site.pk, name=name, kind=body.kind, base_url=body.base_url
        )
    row.kind = body.kind
    row.base_url = body.base_url
    row.api_token = body.api_token
    row.default_engine = body.default_engine
    row.default_langs = ",".join(body.default_langs) or None
    row.default_prompt = body.default_prompt
    row.enabled = body.enabled
    row.updated_at = datetime.now()
    session.add(row)
    session.commit()
    session.refresh(row)
    return _backend_out(row)


@router.delete("/config/{name}", status_code=204)
def delete_config(
    name: str,
    family: str = Query(...),
    code: str = Query(...),
    session: Session = Depends(get_session),
) -> None:
    site = _site_for(session, family, code)
    row = session.exec(
        select(OcrBackendConfig).where(
            OcrBackendConfig.site_pk == site.pk, OcrBackendConfig.name == name
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"no OCR backend {name}")
    session.delete(row)
    session.commit()


# ---- recognition --------------------------------------------------------------


@router.post("/run")
def run_ocr(
    body: OcrRunIn,
    session: Session = Depends(get_session),
    builder: ClientBuilder = Depends(get_client_builder),
) -> OcrRunOut:
    leaf = _page_for(session, body.path)
    configs = [c for c in _configs_for_site(session, leaf.site.pk) if c.enabled]
    if body.backend is not None:
        config = next((c for c in configs if c.name == body.backend), None)
        if config is None:
            raise HTTPException(
                status_code=404, detail=f"no enabled OCR backend {body.backend}"
            )
    elif configs:
        config = configs[0]
    else:
        raise HTTPException(
            status_code=404,
            detail=f"no OCR backend configured for site {leaf.site.family}/{leaf.site.code}",
        )

    # Translate to the backend-reachable image URL: the wiki-side rendition
    # from PageMeta, never the sidecar's localhost /pages/image endpoint.
    meta = PageStore(session).page_meta(leaf.page)
    image_url = None
    if meta is not None:
        image_url = meta.source_image_url or meta.thumb_url

    request = OcrRequest(
        image_url=image_url,
        image_base64=body.image_base64,
        engine=body.engine or config.default_engine,
        langs=body.langs if body.langs is not None else config.langs_list(),
        prompt=body.prompt or config.default_prompt,
    )
    try:
        result = builder(config).recognize(request)
    except OcrError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return OcrRunOut(
        backend=config.name,
        kind=config.kind,
        engine=result.engine,
        text=result.text,
        text_base64=base64.b64encode(result.text.encode()).decode(),
    )
