import logging
import mimetypes
import re
from pathlib import Path

import requests
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Query,
    Request,
    Response,
)
from sqlalchemy import func
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.api.errors import ApiError
from wtbot.deps import get_session
from wtbot.model import Page
from wtbot.model.page_meta import PageMeta
from wtbot.settings import WikiSettings
from wtbot.vfs.nodes import PageLeaf, resolve
from wtbot.vfs.store import PageStore, canonical_title

"""Scan-image bytes for proofread pages.

GET /pages/image?path={wikisource VFS path}&width=N streams the page's scan
rendition. The client never needs a wiki URL (or the wiki's CA/credentials):
the image for an open editor is addressable from the path the editor already
holds. The wiki-side URLs in PageMeta are this endpoint's implementation
detail — used to fill a bytes cache under blob_root on first request, local
forever after. When the raster cache lands (local ddvu/pdftoppm extraction),
only the cache-fill step changes; the contract does not.

Width handling: MediaWiki thumb URLs carry a `page{N}-{W}px-` token, and the
thumb handler renders any width on demand, so one known URL yields every
rendition. No width means the stored reference/fullsize rendition as-is.

Sequential transcription is the normal workflow, so serving page N warms
page N+1 at the same width in the background (best-effort).
"""

router = APIRouter(prefix="/pages", tags=["page-images"], route_class=DebugLoggingRoute)

logger = logging.getLogger(__name__)

_PX_TOKEN = re.compile(r"(page\d+-)(\d+)(px-)")


def fetch_image_bytes(url: str) -> bytes:
    """Module-level so tests monkeypatch it. Fail fast: no retries, and the
    CA bundle for a self-signed local wiki comes from the same env knob the
    pywikibot side uses."""
    verify: bool | str = WikiSettings.from_env().ca_bundle or True
    resp = requests.get(
        url,
        timeout=(5, 30),
        verify=verify,
        headers={"User-Agent": "wtbot (wikisource-plugin)"},
    )
    resp.raise_for_status()
    return resp.content


def _rendition_url(meta: PageMeta | None, width: int | None) -> str | None:
    if meta is None:
        return None
    base = meta.source_image_url or meta.thumb_url
    if base is None:
        return None
    if width is None:
        return base
    rewritten, n = _PX_TOKEN.subn(rf"\g<1>{width}\g<3>", base)
    return rewritten if n else base


def _cache_path(blob_root: Path, page_pk: int, width: int | None, url: str) -> Path:
    ext = Path(url.split("?", 1)[0]).suffix or ".jpg"
    label = str(width) if width is not None else "src"
    return blob_root / "page_images" / f"{page_pk}-{label}{ext}"


def _fill_cache(cache: Path, url: str) -> None:
    data = fetch_image_bytes(url)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(data)


@router.get("/image")
def get_page_image(
    request: Request,
    background: BackgroundTasks,
    path: str = Query(..., description="wikisource:// VFS path of the Page: leaf"),
    width: int | None = Query(None, ge=16, le=4096),
    session: Session = Depends(get_session),
) -> Response:
    store = PageStore(session)
    node = resolve(store, path)
    if not isinstance(node, PageLeaf):
        raise ApiError(
            status_code=404,
            detail=f"not a proofread page: {path}",
            code="not-a-proofread-page",
        )

    response = serve_scan_image(request, background, session, node.page, width)
    if response is None:
        raise ApiError(
            status_code=404,
            detail=f"no scan image known for {node.page.title} — fetch the page first",
            code="no-scan-image",
        )
    return response


def serve_scan_image(
    request: Request,
    background: BackgroundTasks,
    session: Session,
    page: Page,
    width: int | None,
) -> Response | None:
    """Cached scan-rendition bytes for [page], or None while no scan URL is
    known. Shared by GET /pages/image (canonical, 404 on None) and the
    preview pane's GET /preview/page-image (placeholder SVG on None)."""
    store = PageStore(session)
    meta = store.page_meta(page)
    url = _rendition_url(meta, width)
    if url is None:
        return None

    blob_root = Path(request.app.state.blob_root)
    cache = _cache_path(blob_root, page.pk, width, url)
    if not cache.exists():
        try:
            _fill_cache(cache, url)
        except Exception as exc:  # noqa: BLE001 - surface as bad gateway
            raise ApiError(
                status_code=502,
                detail=f"scan image fetch failed: {exc}",
                code="scan-image-fetch-failed",
            ) from exc

    background.add_task(
        _warm_next_page,
        request.app.state.engine,
        blob_root,
        page.site_pk,
        meta.index_title if meta is not None else None,
        meta.page_number if meta is not None else None,
        width,
    )

    media_type = mimetypes.guess_type(cache.name)[0] or "image/jpeg"
    return Response(content=cache.read_bytes(), media_type=media_type)


def _warm_next_page(
    engine,
    blob_root: Path,
    site_pk: int,
    index_title: str | None,
    page_number: int | None,
    width: int | None,
) -> None:
    """Best-effort pre-fetch of the next page's rendition — sequential
    transcription assumes that is the page opened next."""
    if index_title is None or page_number is None:
        return
    try:
        with Session(engine) as session:
            nxt = session.exec(
                select(Page)
                .join(PageMeta, PageMeta.page_pk == Page.pk)
                .where(
                    Page.site_pk == site_pk,
                    func.replace(PageMeta.index_title, "_", " ")
                    == canonical_title(index_title),
                    PageMeta.page_number == page_number + 1,
                )
            ).first()
            if nxt is None or nxt.pk is None:
                return
            url = _rendition_url(PageStore(session).page_meta(nxt), width)
            cache = _cache_path(blob_root, nxt.pk, width, url) if url else None
        if url is None or cache is None or cache.exists():
            return
        _fill_cache(cache, url)
    except Exception as exc:  # noqa: BLE001 - warming must never surface
        logger.debug("next-page warm failed: %s", exc)
