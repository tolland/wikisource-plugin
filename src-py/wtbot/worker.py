"""Fetch worker: drains the FetchRequest queue, calls the wiki, writes results
back into the cache.

Kept as plain functions over a Session + a client factory so it is fully
testable with FakeWikiClient and reusable from either the API (inline, today) or
a future background loop / ``wtbot worker`` command.
"""

import re
from collections.abc import Callable
from pathlib import Path

from sqlmodel import Session, select

from wtbot.settings import WikiSettings
from wtbot.sqlmodel import (
    FetchRequest,
    FetchState,
    FetchStatus,
    FileBlob,
    Page,
    Site,
    role_for_canonical,
)
from wtbot.sqlmodel.fetch_request import FetchKind
from wtbot.sqlmodel.namespace import NsRole
from wtbot.timeutil import utcnow
from wtbot.wiki.client import WikiClient, get_wiki_client
from wtbot.wiki.namespaces import sync_namespaces
from wtbot.wiki.wiki_types import PageNotFound, RemotePage

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


def _maybe_sync_namespaces(session: Session, site: Site, client: WikiClient) -> None:
    """Sync siteinfo namespaces on first use of a site (no-op on subsequent calls)."""
    from wtbot.sqlmodel import Namespace

    already = session.exec(
        select(Namespace).where(Namespace.site_pk == site.pk)
    ).first()
    if already is not None:
        return
    ns_dict = client.get_namespaces()
    if ns_dict is None:
        return
    sync_namespaces(session, site, ns_dict)


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
        _maybe_sync_namespaces(session, site, client)
        remote = client.get_page(req.title)
        page = _upsert_page(session, site, remote)

        # Drive behaviour from what was actually fetched, not from req.kind.
        role = role_for_canonical(remote.namespace_canonical or "")
        if role == NsRole.file:
            # File: pages report content_model='wikitext' (the description page)
            # but the real payload is the binary blob — always download it.
            _download_file_blob(session, site, page, remote.title, client, blob_root)
            req.progress_total = 1
            req.progress_done = 1
            req.status = FetchStatus.done
        elif remote.content_model == "proofread-index" and req.depth > 0:
            child_count = _fan_out_index(session, site, req, page, client, blob_root)
            req.progress_total = 1 + child_count
            req.progress_done = 1
            req.status = (
                FetchStatus.in_progress if child_count > 0 else FetchStatus.done
            )
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
    if (
        req.status in (FetchStatus.done, FetchStatus.error)
        and req.parent_pk is not None
    ):
        _update_parent_progress(session, req)

    session.commit()


def _update_parent_progress(session: Session, child_req: FetchRequest) -> None:
    """Increment parent.progress_done; mark done when all children have finished."""
    parent = session.get(FetchRequest, child_req.parent_pk)
    if parent is None:
        return
    parent.progress_done = (parent.progress_done or 0) + 1
    if (
        parent.progress_total is not None
        and parent.progress_done >= parent.progress_total
    ):
        parent.status = FetchStatus.done
    parent.updated_at = utcnow()
    session.add(parent)
    # Caller commits.


def _download_file_blob(
    session: Session,
    site: Site,
    page: Page,
    file_title: str,
    client: WikiClient,
    blob_root: Path | None,
) -> None:
    """Fetch imageinfo + download binary for a File: page; upsert a FileBlob row."""
    if page.pk is None:
        return  # page must already be persisted

    dest = _blob_path(blob_root, site, file_title)
    try:
        info = client.get_file_info(file_title)
        actual = client.download_file(file_title, dest)
    except PageNotFound:
        return  # blob not available; proceed without FileBlob

    blob = session.exec(select(FileBlob).where(FileBlob.page_pk == page.pk)).first()
    if blob is None:
        blob = FileBlob(page_pk=page.pk)

    blob.file_sha1 = info.file_sha1
    blob.size = info.size
    blob.mime = info.mime
    blob.url = info.url
    blob.upload_timestamp = info.upload_timestamp
    blob.uploader = info.uploader
    blob.upload_comment = info.upload_comment
    blob.page_count = info.page_count
    blob.width = info.width
    blob.height = info.height
    blob.local_path = str(actual)
    blob.downloaded_at = utcnow()

    session.add(blob)
    session.commit()


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
    _download_file_blob(session, site, index_page, file_title, client, blob_root)

    # Prefer page_count set by _upsert_page (from IndexPage.num_pages via
    # PywikibotClient); fall back to <pagelist> parsing for FakeWikiClient.
    page_count = index_page.page_count or _parse_page_count(index_page.text or "")
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
    ns_role = role_for_canonical(remote.namespace_canonical or "")
    page.namespace_role = ns_role
    page.content_model = remote.content_model
    page.text = remote.text
    page.pageid = remote.pageid
    page.revid = remote.revid
    page.remote_timestamp = remote.timestamp
    page.contributor = remote.user
    page.comment = remote.comment
    page.sha1 = remote.sha1
    # page_count from IndexPage.num_pages (PywikibotClient) takes priority; the
    # <pagelist> fallback in _fan_out_index covers FakeWikiClient in tests.
    if remote.page_count is not None:
        page.page_count = remote.page_count
    # Derive index_title and page_number for ProofreadPage Page: rows.
    # Title is always "Page:{basename}/{n}"; rsplit gives (basename, n).
    if ns_role == NsRole.page and page.index_title is None:
        after_ns = remote.title.split(":", 1)[-1]  # "Foo.pdf/3"
        base, _, num = after_ns.rpartition("/")
        if base and num.isdigit():
            page.index_title = f"Index:{base}"
            page.page_number = int(num)
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
