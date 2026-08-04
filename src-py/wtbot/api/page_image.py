import logging
import mimetypes
import re
from pathlib import Path

import requests
from fastapi import BackgroundTasks, HTTPException, Request, Response
from sqlalchemy import func
from sqlmodel import Session, select

from wtbot.model import Page
from wtbot.model.page_meta import PageMeta
from wtbot.settings import WikiSettings
from wtbot.vfs.store import PageStore, canonical_title

"""Scan-image bytes for proofread pages — the cache-and-serve engine behind
the image route, not a router itself.

`serve_scan_image()` streams a page's scan rendition from a local bytes
cache under blob_root, filling it from the wiki-side URLs in PageMeta on
first request. The client never needs a wiki URL (or the wiki's
CA/credentials): the image for an open editor is addressable from the path
the editor already holds. When the raster cache lands (local ddjvu/pdftoppm
extraction), only the cache-fill step changes; the contract does not.

The HTTP surface is `GET /preview/page-image` (see wtbot.api.preview), which
adds path/title resolution and the placeholder-SVG fallback. A second,
strict `GET /pages/image` route used to live here and had no callers on
either side of the contract; it was removed rather than left to rot. If a
strict (404-on-no-scan) variant is wanted again, it belongs next to the
lenient one as a query flag, not as a separate endpoint.

Width handling: MediaWiki thumb URLs carry a `page{N}-{W}px-` token, and the
thumb handler renders any width on demand, so one known URL yields every
rendition. No width means the stored reference/fullsize rendition as-is.

Sequential transcription is the normal workflow, so serving page N warms
page N+1 at the same width in the background (best-effort).
"""

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


def serve_scan_image(
    request: Request,
    background: BackgroundTasks,
    session: Session,
    page: Page,
    width: int | None,
) -> Response | None:
    """Cached scan-rendition bytes for [page], or None while no scan URL is
    known — the caller decides what a miss means (GET /preview/page-image
    answers with a placeholder SVG)."""
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
            raise HTTPException(
                status_code=502, detail=f"scan image fetch failed: {exc}"
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
        logging.debug("next-page warm failed: %s", exc)
