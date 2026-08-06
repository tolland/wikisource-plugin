import threading

from fastapi import HTTPException, Request
from sqlmodel import Session, select

from wtbot.model import Page, Site
from wtbot.wiki.client import WikiClient

"""Resolving a VFS path to the wiki thing it names.

Shared by the two routers that take a ``wikisource://`` path and have to act
on the page behind it: the live preview (parse this body) and the reference
image (serve this page's scan). It lived in the preview router while that was
the only caller, which is also how the reference image came to be served from
a ``/preview`` path.
"""


def parse_path(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s]


def resolve_target(session: Session, path: str) -> tuple[Site, str, str | None]:
    """Map a VFS path to (site, page title, content model).

    Mirrors the path shapes served by wtbot.api.vfs. The title is derived from
    the path even when the page isn't cached yet, so a preview works before the
    first fetch completes; content model then falls back to title inference on
    the wiki side.
    """
    parts = parse_path(path)
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
