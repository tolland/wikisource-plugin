import base64

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.api.errors import ApiError
from wtbot.api.targets import client_for, resolve_target
from wtbot.deps import get_session
from wtbot.model import Site

"""Live-preview endpoint — renders an unsaved wikitext body to HTML.

Only that. The *reference image* -- the scan of the page being transcribed --
used to be served from ``/preview/page-image``, which called a picture of a
book page a preview. It has its own router now (wtbot.api.reference_image);
what is left here returns rendered markup, which is what a preview is.

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


@router.post("/render", response_model=PreviewResponse)
def render_preview(
    body: PreviewRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> PreviewResponse:
    content_model: str | None = None
    if body.path:
        site, title, content_model = resolve_target(session, body.path)
    else:
        if not body.title:
            raise ApiError(
                status_code=422,
                detail="need either path or title",
                code="missing-target",
            )
        title = body.title
        site = session.exec(select(Site)).first()
        if site is None:
            raise ApiError(
                status_code=404, detail="no site configured", code="no-site-configured"
            )

    # All reads are done. Release the session now rather than holding it
    # across a multi-second wiki round trip on every debounced keystroke.
    session.close()

    client = client_for(request, site)
    try:
        rendered = client.render_preview(title, body.wikitext, content_model)
    except Exception as e:  # wiki/network failures surface as a gateway error
        raise ApiError(
            status_code=502, detail=f"parse failed: {e}", code="wiki-parse-failed"
        ) from e

    return PreviewResponse(
        title=rendered.title,
        html_base64=base64.b64encode(rendered.html.encode()).decode("ascii"),
        server=rendered.server,
        script_path=rendered.script_path,
    )
