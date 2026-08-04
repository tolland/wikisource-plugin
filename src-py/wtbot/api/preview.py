import base64
import logging
import threading
from xml.sax.saxutils import escape

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.api.page_image import serve_scan_image
from wtbot.deps import get_session
from wtbot.model import Page, Site
from wtbot.settings import WikiSettings
from wtbot.wiki.client import WikiClient
from wtbot.wiki.wiki_types import RemotePageImages

"""Live-preview endpoint — renders an unsaved wikitext body to HTML.

This proxies MediaWiki's ``action=parse`` (the same call the browser's live
preview makes) through the sidecar so the plugin never needs wiki credentials,
the LAN CA bundle, or its own HTTP session — all of that already lives here.

The body targets either a VFS path (``wikisource://`` files — resolves the
site, page title and content model from the cache) or a bare title (scratch
``.wt`` files — parsed against the first configured site).
"""

router = APIRouter(prefix="/preview", tags=["preview"], route_class=DebugLoggingRoute)


class PreviewRequest(BaseModel):
    path: str | None = None  # VFS path, e.g. /wikisource/en/Index:X.pdf/Page:X.pdf/1
    title: str | None = None  # used when path is None (local scratch files)
    wikitext: str


class PreviewResponse(BaseModel):
    title: str
    # base64 so the plugin's minimal JSON reader never sees escaped HTML
    html_base64: str
    server: str | None = None  # e.g. 'https://en.wikisource.org' (for stylesheets)
    script_path: str | None = None  # e.g. '/w'


def _parse_path(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s]


def _resolve_target(session: Session, path: str) -> tuple[Site, str, str | None]:
    """Map a VFS path to (site, page title, content model).

    Mirrors the path shapes served by wtbot.api.vfs. The title is derived from
    the path even when the page isn't cached yet, so a preview works before the
    first fetch completes; content model then falls back to title inference on
    the wiki side.
    """
    parts = _parse_path(path)
    if len(parts) < 3:
        raise HTTPException(status_code=422, detail=f"path is not a page: {path}")

    family, code, index_title = parts[0], parts[1], parts[2]
    site = session.exec(
        select(Site).where(Site.family == family, Site.code == code)
    ).first()
    if site is None:
        raise HTTPException(status_code=404, detail=f"site {family}/{code} not found")

    rest = parts[3:]
    if not rest or rest == ["wikitext"]:
        title = index_title  # the Index page's own body
    elif rest[0] == "Pages" and len(rest) > 1:
        title = "/".join(rest[1:])
    elif rest[-1] == "wikitext":
        title = "/".join(rest[:-1])  # File:…/wikitext
    elif ":" in rest[0]:
        title = "/".join(rest)  # namespaced asset directly under the index
    else:
        title = f"{index_title}/{'/'.join(rest)}"  # index subpage, e.g. styles.css

    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == title)
    ).first()
    return site, title, page.content_model if page else None


def _client_for(request: Request, site: Site) -> WikiClient:
    """Per-site client cache. Building a PywikibotClient configures pywikibot
    and may log in, which is far too heavy per keystroke-debounced preview."""
    state = request.app.state
    if not hasattr(state, "preview_clients"):
        state.preview_clients = {}
        state.preview_clients_lock = threading.Lock()
    with state.preview_clients_lock:
        client = state.preview_clients.get(site.pk)
        if client is None:
            client = state.client_factory(site)
            state.preview_clients[site.pk] = client
        return client


@router.post("/render", response_model=PreviewResponse)
def render_preview(
    body: PreviewRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> PreviewResponse:
    content_model: str | None = None
    if body.path:
        site, title, content_model = _resolve_target(session, body.path)
    else:
        if not body.title:
            raise HTTPException(status_code=422, detail="need either path or title")
        title = body.title
        site = session.exec(select(Site)).first()
        if site is None:
            raise HTTPException(status_code=404, detail="no site configured")

    # All reads are done. Release the session now rather than holding it
    # across a multi-second wiki round trip on every debounced keystroke.
    session.close()

    client = _client_for(request, site)
    try:
        rendered = client.render_preview(title, body.wikitext, content_model)
    except Exception as e:  # wiki/network failures surface as a gateway error
        raise HTTPException(status_code=502, detail=f"parse failed: {e}") from e

    return PreviewResponse(
        title=rendered.title,
        html_base64=base64.b64encode(rendered.html.encode()).decode("ascii"),
        server=rendered.server,
        script_path=rendered.script_path,
    )


# Page-ish aspect ratio so the pane's layout matches a real scan later.
_PLACEHOLDER_W, _PLACEHOLDER_H = 800, 1200


def _placeholder_svg(title: str) -> str:
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


def _fetch_image(url: str) -> tuple[bytes, str] | None:
    """One plain GET for the scan raster, no retries: older sources often have
    their backing File: deleted or replaced (dead upload URLs), and that must
    degrade to the placeholder — never a retry loop or a broken image."""
    try:
        import requests

        resp = requests.get(
            url,
            headers={"User-Agent": "wtbot (wikisource-plugin)"},
            timeout=(5, 30),
            verify=WikiSettings.from_env().ca_bundle or True,
        )
    except Exception as exc:  # noqa: BLE001 - degrade to placeholder
        logging.debug("page-image fetch failed for %s: %s", url, exc)
        return None
    content_type = resp.headers.get("content-type", "")
    if resp.status_code != 200 or not content_type.startswith("image/"):
        logging.debug(
            "page-image fetch for %s: HTTP %s, content-type %r",
            url,
            resp.status_code,
            content_type,
        )
        return None
    return resp.content, content_type


def _live_page_images(
    request: Request, site: Site, title: str
) -> RemotePageImages | None:
    """Single fail-fast ``prop=imageforpage`` lookup; never raises. Client
    construction failures count as a miss, like every other failure here."""
    try:
        return _client_for(request, site).get_page_images(title)
    except Exception as exc:  # noqa: BLE001 - enrichment only, never fatal
        logging.debug("live imageforpage lookup failed for %s: %s", title, exc)
        return None


@router.get("/page-image")
def page_image(
    request: Request,
    background: BackgroundTasks,
    path: str | None = None,
    title: str | None = None,
    width: int | None = None,
    session: Session = Depends(get_session),
) -> Response:
    """Reference scan image for a Page: (the transcription workflow's source).

    Serves the real scan rendition (cached bytes via wtbot.api.page_image,
    fed by the imageforpage URLs the fetch worker stored) when one is known,
    and degrades to a generated placeholder SVG labelled with the page title
    while it is not — an unfetched page still gets a split pane, just an
    empty one. This is the only image endpoint: a strict sibling under
    /pages/image existed and had no callers, so a future strict mode belongs
    here as a query flag rather than as a second route.
    """
    page: Page | None = None
    if path:
        site, resolved_title, _ = _resolve_target(session, path)
        page = session.exec(
            select(Page).where(Page.site_pk == site.pk, Page.title == resolved_title)
        ).first()
    elif title:
        resolved_title = title
        page = session.exec(select(Page).where(Page.title == title)).first()
    else:
        raise HTTPException(status_code=422, detail="need either path or title")

    if page is not None:
        response = serve_scan_image(request, background, session, page, width)
        if response is not None:
            return response

    return Response(
        content=_placeholder_svg(resolved_title),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},  # placeholder until fetched
    )
