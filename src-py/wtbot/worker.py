"""Fetch worker: drains the FetchRequest queue, calls the wiki, writes results
back into the cache.

Kept as plain functions over a Session + a client factory so it is fully
testable with FakeWikiClient and reusable from either the API (inline, today) or
a future background loop / ``wtbot worker`` command.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

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
from wtbot.sqlmodel.fetch_request import FetchKind
from wtbot.timeutil import utcnow
from wtbot.wiki.client import WikiClient, get_wiki_client
from wtbot.wiki.types import PageNotFound, RemotePage

ClientFactory = Callable[[Site], WikiClient]


def make_client_for_site(site: Site) -> WikiClient:
    return get_wiki_client(WikiSettings.from_site(site))


def run_pending(
    session: Session,
    client_factory: ClientFactory,
    *,
    limit: int = 100,
    blob_root: Path | None = None,
) -> int:
    """Process up to ``limit`` pending requests. Returns how many were handled."""
    handled = 0
    while handled < limit:
        req = _claim_next(session)
        if req is None:
            break
        _process(session, req, client_factory, blob_root=blob_root)
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
    session: Session,
    req: FetchRequest,
    client_factory: ClientFactory,
    *,
    blob_root: Path | None = None,
) -> None:
    site = session.get(Site, req.site_pk)
    try:
        client = client_factory(site)
        remote = client.get_page(req.title)
        page = _upsert_page(session, site, remote)

        if req.kind == FetchKind.index and req.depth > 0:
            child_count = _fan_out_index(session, site, req, page, client, blob_root)
            req.progress_total = 1 + child_count
            req.progress_done = 1
            req.status = FetchStatus.in_progress if child_count > 0 else FetchStatus.done
        else:
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

    # Propagate completion to the parent (if this is a child request).
    if req.status in (FetchStatus.done, FetchStatus.error) and req.parent_pk is not None:
        _update_parent_progress(session, req)

    session.commit()


def _update_parent_progress(session: Session, child_req: FetchRequest) -> None:
    """Increment parent.progress_done; mark done when all children have finished."""
    parent = session.get(FetchRequest, child_req.parent_pk)
    if parent is None:
        return
    parent.progress_done = (parent.progress_done or 0) + 1
    if parent.progress_total is not None and parent.progress_done >= parent.progress_total:
        parent.status = FetchStatus.done
    parent.updated_at = utcnow()
    session.add(parent)
    # Caller commits.


def _fan_out_index(
    session: Session,
    site: Site,
    req: FetchRequest,
    index_page: Page,
    client: WikiClient,
    blob_root: Path | None,
) -> int:
    """Download the File: blob, parse page count, enqueue per-page children.

    Returns the number of child FetchRequests created (0 if page count unknown).
    """
    file_title = _index_to_file_title(req.title)

    # Try to download the backing file blob.
    dest = _blob_path(blob_root, site, file_title)
    try:
        actual = client.download_file(file_title, dest)
        index_page.file_ref = str(actual)
        session.add(index_page)
        session.commit()
        session.refresh(index_page)
    except PageNotFound:
        pass  # file not available yet; proceed without blob

    page_count = _parse_page_count(index_page.body or "")
    if not page_count:
        return 0

    index_page.page_count = page_count
    session.add(index_page)

    basename = _index_basename(req.title)
    for n in range(1, page_count + 1):
        child = FetchRequest(
            site_pk=req.site_pk,
            parent_pk=req.pk,
            title=f"Page:{basename}/{n}",
            kind=FetchKind.page,
            depth=0,
        )
        session.add(child)

    session.commit()
    return page_count


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
    page.dirty = False
    page.fetch_status = FetchState.done
    page.fetch_error = None

    session.add(page)
    session.commit()
    session.refresh(page)
    return page


# ---------------------------------------------------------------------------
# Title helpers
# ---------------------------------------------------------------------------


def _index_basename(title: str) -> str:
    """'Index:Foo.djvu' → 'Foo.djvu'"""
    _, _, rest = title.partition(":")
    return rest


def _index_to_file_title(title: str) -> str:
    """'Index:Foo.djvu' → 'File:Foo.djvu'"""
    return "File:" + _index_basename(title)


def _blob_path(blob_root: Path | None, site: Site, file_title: str) -> Path:
    root = blob_root if blob_root is not None else Path("./blobs")
    filename = file_title.split(":", 1)[-1].replace("/", "_")
    return root / site.family / site.code / filename


# ---------------------------------------------------------------------------
# Pagelist parsing
# ---------------------------------------------------------------------------


def _parse_page_count(body: str) -> int | None:
    """Extract total page count from a ProofreadPage <pagelist> tag.

    Handles ``<pagelist to="N" .../>`` (explicit total) and the implicit form
    where the maximum range bound is the page count.
    """
    m = re.search(r"<pagelist\b([^>]*)/>", body, re.IGNORECASE)
    if not m:
        return None
    attrs = m.group(1)

    to_m = re.search(r'\bto="(\d+)"', attrs)
    if to_m:
        return int(to_m.group(1))

    # Fall back: max of all numeric range keys (NtoM or N).
    nums = []
    for start, end in re.findall(r"\b(\d+)(?:to(\d+))?\s*=", attrs):
        nums.append(int(end) if end else int(start))
    return max(nums) if nums else None
