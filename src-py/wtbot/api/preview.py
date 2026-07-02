import base64
import threading

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from wtbot.api.debug_loggig_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.model import Page, Site
from wtbot.wiki.client import WikiClient

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

    # All reads are done. Release the session's transaction now: _on_begin
    # opens every transaction BEGIN IMMEDIATE (even read-only ones), so keeping
    # it open would (a) deadlock against the client factory's credential
    # lookup on its own connection and (b) hold the IPC write lock across a
    # multi-second wiki round trip on every debounced keystroke.
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
