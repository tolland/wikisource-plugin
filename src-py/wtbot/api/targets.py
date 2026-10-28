import threading

from fastapi import Request
from sqlmodel import Session, select

from wtbot.api.errors import ApiError
from wtbot.model import Site
from wtbot.vfs.paths import WikiPath
from wtbot.vfs.store import PageStore
from wtbot.wiki.client import WikiClient

"""Resolving a VFS path to the wiki thing it names.

Shared by the two routers that take a ``wikisource://`` path and have to act
on the page behind it: the live preview (parse this body) and the reference
image (serve this page's scan). It lived in the preview router while that was
the only caller, which is also how the reference image came to be served from
a ``/preview`` path.
"""


def resolve_target(session: Session, path: str) -> tuple[Site, str, str | None]:
    """Map a VFS path to (site, page title, content model).

    Accepts a title node or any of its aspects (`/f/c/Page/Foo.djvu/8` or
    `.../@wikitext`). The title is derived from the path even when the page
    isn't cached yet, so a preview works before the first fetch completes;
    content model then falls back to title inference on the wiki side.
    """
    parsed = WikiPath.parse(path)
    if len(parsed.segments) < 4 or not parsed.title_rest:
        raise ApiError(
            status_code=422,
            detail=f"path is not a page: {path}",
            code="path-not-a-page",
        )

    site = session.exec(
        select(Site).where(Site.family == parsed.family, Site.code == parsed.code)
    ).first()
    if site is None:
        raise ApiError(
            status_code=404,
            detail=f"site {parsed.family}/{parsed.code} not found",
            code="site-not-found",
        )

    store = PageStore(session)
    ns = store.site_namespaces(site).by_segment(parsed.namespace_segment)
    if ns is None:
        raise ApiError(
            status_code=404,
            detail=f"namespace {parsed.namespace_segment!r} not found on "
            f"{parsed.family}/{parsed.code}",
            code="namespace-not-found",
        )
    title = ns.title(parsed.title_rest)

    # The title's expectation, which a fetch keeps equal to the wiki's own
    # answer: a page the wiki does not hold yet still renders as what it is.
    known = store.entry(site, title)
    return site, title, known.content_model if known else None


_lock = threading.Lock()


def client_for(request: Request, site: Site) -> WikiClient:
    """The wiki client for a site.

    Thin now: ``app.state.client_factory`` memoizes per (site, credential)
    since the client registry landed, so this no longer keeps a cache of its
    own. It did, once -- building a client configures pywikibot and logs in,
    which is far too heavy per keystroke-debounced preview -- and that second
    cache outlived the problem it solved.
    """
    with _lock:
        return request.app.state.client_factory(site)
