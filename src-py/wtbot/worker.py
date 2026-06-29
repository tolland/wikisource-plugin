"""Fetch worker: drains the FetchRequest queue, calls the wiki, writes results
back into the cache.

Kept as plain functions over a Session + a client factory so it is fully
testable with FakeWikiClient and reusable from either the API (inline, today) or
a future background loop / ``wtbot worker`` command.

This first cut handles a single title per request (fetch -> upsert Page). Index
fan-out (download the File: blob, parse <pagelist>, create per-page children) is
the next increment and slots in at the marked point in ``_process``.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlmodel import Session, select

from wtbot.settings import WikiSettings
from wtbot.sqlmodel import (
    FetchRequest,
    FetchState,
    FetchStatus,
    Page,
    Site,
    role_for_canonical,
)
from wtbot.timeutil import utcnow
from wtbot.wiki.client import WikiClient, get_wiki_client
from wtbot.wiki.types import PageNotFound, RemotePage

# A client factory lets tests inject FakeWikiClient; production builds a real one
# from the Site row.
ClientFactory = Callable[[Site], WikiClient]


def make_client_for_site(site: Site) -> WikiClient:
    return get_wiki_client(WikiSettings.from_site(site))


def run_pending(
    session: Session, client_factory: ClientFactory, *, limit: int = 100
) -> int:
    """Process up to ``limit`` pending requests. Returns how many were handled."""
    handled = 0
    while handled < limit:
        req = _claim_next(session)
        if req is None:
            break
        _process(session, req, client_factory)
        handled += 1
    return handled


def _claim_next(session: Session) -> FetchRequest | None:
    req = session.exec(
        select(FetchRequest)
        .where(FetchRequest.status == FetchStatus.pending)
        .order_by(FetchRequest.priority.desc(), FetchRequest.requested_at)
    ).first()
    if req is None:
        return None
    req.status = FetchStatus.in_progress
    req.updated_at = utcnow()
    session.add(req)
    session.commit()
    session.refresh(req)
    return req


def _process(
    session: Session, req: FetchRequest, client_factory: ClientFactory
) -> None:
    site = session.get(Site, req.site_pk)
    try:
        client = client_factory(site)
        remote = client.get_page(req.title)
        _upsert_page(session, site, remote)

        # --- Index fan-out goes here (next increment): for a proofread-index
        # with depth > 0, download the File: blob, read page_count, and create
        # child `page` FetchRequests with parent_pk = req.pk. ---

        req.progress_total = 1
        req.progress_done = 1
        req.status = FetchStatus.done
        req.error_message = None
    except PageNotFound:
        req.status = FetchStatus.error
        req.error_message = f"page not found: {req.title}"
    except Exception as exc:  # noqa: BLE001 - record any failure on the row
        req.status = FetchStatus.error
        req.error_message = f"{type(exc).__name__}: {exc}"
    req.updated_at = utcnow()
    session.add(req)
    session.commit()


def _upsert_page(session: Session, site: Site, remote: RemotePage) -> Page:
    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == remote.title)
    ).first()
    if page is None:
        page = Page(site_pk=site.pk, title=remote.title)

    page.namespace_key = remote.namespace_key
    page.namespace_role = role_for_canonical(remote.namespace_canonical or "")
    page.content_model = remote.content_model
    page.body = remote.text
    page.pageid = remote.pageid
    page.revid = remote.revid
    page.remote_timestamp = remote.timestamp
    page.contributor = remote.user
    page.comment = remote.comment
    page.sha1 = remote.sha1
    # A fetch reflects remote state, so the cached body is clean.
    page.dirty = False
    page.fetch_status = FetchState.done
    page.fetch_error = None

    session.add(page)
    session.commit()
    session.refresh(page)
    return page
