"""Fetch worker: drains the FetchRequest queue, calls the wiki, writes results
back into the cache.

Kept as plain functions over a Session + a client factory so it is fully
testable with FakeWikiClient and reusable from either the API (inline, today) or
a future background loop / ``wtbot worker`` command.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
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


@dataclass(frozen=True)
class _ClaimedFetchRequest:
    pk: int
    site_pk: int
    parent_pk: int | None
    title: str
    kind: FetchKind
    depth: int


@dataclass(frozen=True)
class _CachedPage:
    pk: int
    title: str
    namespace_role: NsRole
    content_model: str | None
    text: str | None
    page_count: int | None


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


def _claim_next(session: Session) -> _ClaimedFetchRequest | None:
    try:
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
        claimed = _snapshot_request(req)
        session.commit()
        return claimed
    finally:
        # A SELECT opens BEGIN IMMEDIATE in this app. The worker must not carry
        # that transaction into pywikibot network calls.
        session.rollback()


def _snapshot_request(req: FetchRequest) -> _ClaimedFetchRequest:
    if req.pk is None:
        raise RuntimeError("cannot process an unpersisted fetch request")
    return _ClaimedFetchRequest(
        pk=req.pk,
        site_pk=req.site_pk,
        parent_pk=req.parent_pk,
        title=req.title,
        kind=req.kind,
        depth=req.depth,
    )


def _maybe_sync_namespaces(session: Session, site: Site, client: WikiClient) -> None:
    """Sync siteinfo namespaces on first use of a site (no-op on subsequent calls)."""
    from wtbot.sqlmodel import Namespace

    try:
        already = session.exec(
            select(Namespace).where(Namespace.site_pk == site.pk)
        ).first()
    finally:
        session.rollback()
    if already is not None:
        return
    ns_dict = client.get_namespaces()
    if ns_dict is None:
        return
    sync_namespaces(session, site, ns_dict)
    session.rollback()


def _process(
    session: Session,
    req: _ClaimedFetchRequest,
    client_factory: ClientFactory,
    *,
    blob_root: Path | None = None,
) -> None:
    site = _load_site_snapshot(session, req.site_pk)
    status = FetchStatus.error
    progress_total = None
    progress_done = 0
    error_message = None
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
            progress_total = 1
            progress_done = 1
            status = FetchStatus.done
        elif remote.content_model == "proofread-index" and req.depth > 0:
            child_count = _fan_out_index(session, site, req, page, client, blob_root)
            progress_total = 1 + child_count
            progress_done = 1
            status = FetchStatus.in_progress if child_count > 0 else FetchStatus.done
        else:
            progress_total = 1
            progress_done = 1
            status = FetchStatus.done
    except PageNotFound:
        error_message = f"page not found: {req.title}"
    except Exception as exc:  # noqa: BLE001 - record any failure on the row
        error_message = f"{type(exc).__name__}: {exc}"

    _record_fetch_result(
        session,
        req,
        status=status,
        progress_total=progress_total,
        progress_done=progress_done,
        error_message=error_message,
    )


def _load_site_snapshot(session: Session, site_pk: int) -> Site:
    try:
        site = session.get(Site, site_pk)
        if site is None:
            raise RuntimeError(f"fetch request references missing site {site_pk}")
        return Site(
            pk=site.pk,
            family=site.family,
            code=site.code,
            articlepath=site.articlepath,
            host=site.host,
            api_url=site.api_url,
            label=site.label,
            created_at=site.created_at,
        )
    finally:
        session.rollback()


def _record_fetch_result(
    session: Session,
    req: _ClaimedFetchRequest,
    *,
    status: FetchStatus,
    progress_total: int | None,
    progress_done: int,
    error_message: str | None,
) -> None:
    try:
        db_req = session.get(FetchRequest, req.pk)
        if db_req is None:
            return
        db_req.status = status
        db_req.progress_total = progress_total
        db_req.progress_done = progress_done
        db_req.error_message = error_message
        db_req.updated_at = utcnow()
        session.add(db_req)

        # Propagate completion to the parent (if this is a child request).
        if (
            status in (FetchStatus.done, FetchStatus.error)
            and req.parent_pk is not None
        ):
            _update_parent_progress(session, req.parent_pk)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.rollback()


def _update_parent_progress(session: Session, parent_pk: int) -> None:
    """Increment parent.progress_done; mark done when all children have finished."""
    parent = session.get(FetchRequest, parent_pk)
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
    page: _CachedPage,
    file_title: str,
    client: WikiClient,
    blob_root: Path | None,
) -> None:
    """Fetch imageinfo + download binary for a File: page; upsert a FileBlob row."""
    dest = _blob_path(blob_root, site, file_title)
    try:
        info = client.get_file_info(file_title)
        actual = client.download_file(file_title, dest)
    except PageNotFound:
        return  # blob not available; proceed without FileBlob

    try:
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
    except Exception:
        session.rollback()
        raise
    finally:
        session.rollback()


def _fan_out_index(
    session: Session,
    site: Site,
    req: _ClaimedFetchRequest,
    index_page: _CachedPage,
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

    try:
        db_index_page = session.get(Page, index_page.pk)
        if db_index_page is not None:
            db_index_page.page_count = page_count
            session.add(db_index_page)

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
    except Exception:
        session.rollback()
        raise
    finally:
        session.rollback()


def _upsert_page(session: Session, site: Site, remote: RemotePage) -> _CachedPage:
    try:
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
        # page_count from IndexPage.num_pages (PywikibotClient) takes priority;
        # the <pagelist> fallback in _fan_out_index covers FakeWikiClient tests.
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
        session.flush()
        if page.pk is None:
            raise RuntimeError(f"page {remote.title!r} did not get a primary key")
        cached = _CachedPage(
            pk=page.pk,
            title=page.title,
            namespace_role=page.namespace_role,
            content_model=page.content_model,
            text=page.text,
            page_count=page.page_count,
        )
        session.commit()
        return cached
    except Exception:
        session.rollback()
        raise
    finally:
        session.rollback()


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
