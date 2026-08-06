import logging
import mimetypes
import re
from pathlib import Path
from xml.sax.saxutils import escape

import requests
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Request,
    Response,
)
from sqlalchemy import func
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.api.targets import resolve_target
from wtbot.deps import get_session
from wtbot.model import Page
from wtbot.model.page_meta import PageMeta
from wtbot.settings import WikiSettings
from wtbot.vfs.store import PageStore, canonical_title

"""The reference image: the scan of the page being transcribed.

``GET /reference-image?path=…`` (or ``?title=``) serves the picture the
transcriber is reading from -- what ProofreadPage's API calls
``prop=imageforpage``. It is *not* a preview, and it used to be served from
``/preview/page-image``, which said it was one. The preview endpoint next door
renders wikitext to HTML through ``action=parse`` and returns markup; this
returns pixels of a scanned page. Two different things, and the split editor
shows them in different panes.

`serve_reference_image()` streams a page's scan rendition from a local bytes
cache under blob_root, filling it from the wiki-side URLs in PageMeta on
first request. The client never needs a wiki URL (or the wiki's
CA/credentials): the image for an open editor is addressable from the path
the editor already holds. When the raster cache lands (local ddjvu/pdftoppm
extraction), only the cache-fill step changes; the contract does not.

A second, strict `GET /pages/image` route used to live here and had no callers
on either side of the contract; it was removed rather than left to rot. If a
strict (404-on-no-scan) variant is wanted again, it belongs next to the
lenient one as a query flag, not as a separate endpoint.

Width handling: MediaWiki thumb URLs carry a `page{N}-{W}px-` token, and the
thumb handler renders any width on demand, so one known URL yields every
rendition. No width means the stored reference/fullsize rendition as-is.

Sequential transcription is the normal workflow, so serving page N warms
page N+1 at the same width in the background (best-effort).
"""

router = APIRouter(
    prefix="/reference-image", tags=["reference-image"], route_class=DebugLoggingRoute
)

_PX_TOKEN = re.compile(r"(page\d+-)(\d+)(px-)")

# Page-ish aspect ratio, so a page with no scan yet lays out like one that has.
_PLACEHOLDER_W = 800
_PLACEHOLDER_H = 1100


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


def serve_reference_image(
    request: Request,
    background: BackgroundTasks,
    session: Session,
    page: Page,
    width: int | None,
) -> Response | None:
    """Cached scan-rendition bytes for [page], or None while no scan URL is
    known — the caller decides what a miss means (the route below answers with
    a placeholder SVG)."""
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


def _placeholder_svg(title: str) -> str:
    """What to show while a page has no scan yet.

    An empty pane would read as a broken image; this reads as "not fetched",
    labelled with the title so it is obvious *which* page is waiting.
    """
    label = escape(title)
    return f"""<svg xmlns="http://www.w3.org/2000/svg"
     width="{_PLACEHOLDER_W}" height="{_PLACEHOLDER_H}"
     viewBox="0 0 {_PLACEHOLDER_W} {_PLACEHOLDER_H}">
  <rect width="100%" height="100%" fill="#f8f4e8"/>
  <rect x="8" y="8" width="{_PLACEHOLDER_W - 16}" height="{_PLACEHOLDER_H - 16}"
        fill="none" stroke="#b0a890" stroke-width="2" stroke-dasharray="12 8"/>
  <line x1="8" y1="8" x2="{_PLACEHOLDER_W - 8}" y2="{_PLACEHOLDER_H - 8}"
        stroke="#e0d8c4" stroke-width="2"/>
  <line x1="{_PLACEHOLDER_W - 8}" y1="8" x2="8" y2="{_PLACEHOLDER_H - 8}"
        stroke="#e0d8c4" stroke-width="2"/>
  <text x="50%" y="46%" text-anchor="middle"
        font-family="sans-serif" font-size="28" fill="#6b6250">{label}</text>
  <text x="50%" y="52%" text-anchor="middle"
        font-family="sans-serif" font-size="20" fill="#8a8069">reference scan not available yet</text>
</svg>
"""


@router.get("")
def reference_image(
    request: Request,
    background: BackgroundTasks,
    path: str | None = None,
    title: str | None = None,
    width: int | None = None,
    session: Session = Depends(get_session),
) -> Response:
    """The scan of the page being transcribed, by VFS path or by title.

    Serves the real rendition (cached bytes, fed by the imageforpage URLs the
    fetch worker stored) when one is known, and degrades to a labelled
    placeholder while it is not -- an unfetched page still gets a pane, just an
    empty one. Never 404s on a missing scan: the pane is part of the editor
    layout, and a broken image there is worse than a blank sheet.
    """
    page: Page | None = None
    if path:
        site, resolved_title, _ = resolve_target(session, path)
        page = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == resolved_title)
        ).first()
    elif title:
        resolved_title = title
        page = session.exec(select(Page).where(Page.title == title)).first()
    else:
        raise HTTPException(status_code=422, detail="need either path or title")

    if page is not None:
        response = serve_reference_image(request, background, session, page, width)
        if response is not None:
            return response

    return Response(
        content=_placeholder_svg(resolved_title),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},  # placeholder until fetched
    )
