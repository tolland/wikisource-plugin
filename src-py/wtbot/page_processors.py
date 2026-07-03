import re
from dataclasses import dataclass
from pathlib import Path

from sqlmodel import Session, select

from wtbot.model import FileBlob, Page, Site, role_for_canonical
from wtbot.model.fetch_request import FetchKind, FetchRequest, FetchStatus
from wtbot.model.namespace import NsRole
from wtbot.model.page_meta import PageMeta
from wtbot.timeutil import utcnow
from wtbot.wiki.client import WikiClient
from wtbot.wiki.wiki_types import PageNotFound, RemotePage, RemotePageImages

"""Per-page-type fetch processing.

The worker fetches a RemotePage and upserts the common Page fields; what
happens *around* that differs by page type. Each type gets a processor
class implementing [PageProcessor]:

  ProofreadPageProcessor   Page:  — derive index_title/page_number, pull the
                           scan image URLs + quality (prop=imageforpage)
                           into PageMeta / Page.quality_level
  ProofreadIndexProcessor  Index: — page_count, File: blob, child fan-out
  IndexAssetProcessor      Index:Foo.djvu/styles.css — link to its index
  FilePageProcessor        File:  — download the binary blob
  DefaultProcessor         anything else

Selection ([processor_for]) is by content_model first — a Page: is a Page:
because it says proofread-page, wherever the namespace landed — with the
File: namespace as a structural override (its content_model is 'wikitext'
for the description page but the real payload is the binary).
"""


@dataclass(frozen=True)
class ClaimedFetchRequest:
    """Detached snapshot of a FetchRequest row, safe to carry across the
    network calls that happen while no transaction is open."""

    pk: int
    site_pk: int
    parent_pk: int | None
    title: str
    kind: FetchKind
    depth: int


@dataclass(frozen=True)
class CachedPage:
    """Detached snapshot of the upserted Page row."""

    pk: int
    title: str
    namespace_role: NsRole
    content_model: str | None
    text: str | None
    page_count: int | None


@dataclass(frozen=True)
class ProcessContext:
    session: Session
    site: Site
    client: WikiClient
    request: ClaimedFetchRequest
    blob_root: Path | None


@dataclass(frozen=True)
class ProcessOutcome:
    status: FetchStatus
    progress_total: int | None = 1
    progress_done: int = 1


_DONE = ProcessOutcome(FetchStatus.done)


class PageProcessor:
    """Base processor: no enrichment, no side effects."""

    def enrich(self, page: Page, remote: RemotePage) -> None:
        """Adjust type-specific Page columns. Runs inside the upsert
        transaction; must not touch the network or the session."""

    def postprocess(
        self, ctx: ProcessContext, cached: CachedPage, remote: RemotePage
    ) -> ProcessOutcome:
        """Side effects after the row is cached: blobs, metadata, fan-out.
        Runs outside any transaction; opens its own short ones."""
        return _DONE


class DefaultProcessor(PageProcessor):
    pass


class ProofreadPageProcessor(PageProcessor):
    def enrich(self, page: Page, remote: RemotePage) -> None:
        # Title is always "Page:{basename}/{n}"; rsplit gives (basename, n).
        if page.index_title is None:
            after_ns = remote.title.split(":", 1)[-1]  # "Foo.pdf/3"
            base, _, num = after_ns.rpartition("/")
            if base and num.isdigit():
                page.index_title = f"Index:{base}"
                page.page_number = int(num)

    def postprocess(
        self, ctx: ProcessContext, cached: CachedPage, remote: RemotePage
    ) -> ProcessOutcome:
        images = ctx.client.get_page_images(cached.title)
        if images is not None:
            _store_page_images(ctx.session, cached.pk, images)
        return _DONE


class ProofreadIndexProcessor(PageProcessor):
    def enrich(self, page: Page, remote: RemotePage) -> None:
        # page_count from IndexPage.num_pages (PywikibotClient) takes priority;
        # the <pagelist> fallback in postprocess covers FakeWikiClient tests.
        if remote.page_count is not None:
            page.page_count = remote.page_count

    def postprocess(
        self, ctx: ProcessContext, cached: CachedPage, remote: RemotePage
    ) -> ProcessOutcome:
        if ctx.request.depth <= 0:
            return _DONE
        child_count = _fan_out_index(ctx, cached)
        return ProcessOutcome(
            status=FetchStatus.in_progress if child_count > 0 else FetchStatus.done,
            progress_total=1 + child_count,
            progress_done=1,
        )


class IndexAssetProcessor(PageProcessor):
    """Index namespace subpages such as Index:Foo.pdf/styles.css are assets
    of the proofread index, not proofread indexes themselves."""

    def enrich(self, page: Page, remote: RemotePage) -> None:
        if page.index_title is None:
            parent_title, _, _ = remote.title.rpartition("/")
            if parent_title:
                page.index_title = parent_title


class FilePageProcessor(PageProcessor):
    """File: pages report content_model='wikitext' (the description page)
    but the real payload is the binary blob — always download it."""

    def postprocess(
        self, ctx: ProcessContext, cached: CachedPage, remote: RemotePage
    ) -> ProcessOutcome:
        download_file_blob(
            ctx.session, ctx.site, cached, cached.title, ctx.client, ctx.blob_root
        )
        return _DONE


_DEFAULT = DefaultProcessor()
_PROOFREAD_PAGE = ProofreadPageProcessor()
_PROOFREAD_INDEX = ProofreadIndexProcessor()
_INDEX_ASSET = IndexAssetProcessor()
_FILE = FilePageProcessor()


def processor_for(remote: RemotePage) -> PageProcessor:
    """Select by what was actually fetched, never by the request's kind."""
    role = role_for_canonical(remote.namespace_canonical or "")
    if role == NsRole.file:
        return _FILE
    if remote.content_model == "proofread-index":
        return _PROOFREAD_INDEX
    if remote.content_model == "proofread-page":
        return _PROOFREAD_PAGE
    if role == NsRole.index:
        return _INDEX_ASSET
    return _DEFAULT


# ---------------------------------------------------------------------------
# Shared side-effect helpers
# ---------------------------------------------------------------------------


def _store_page_images(
    session: Session, page_pk: int, images: RemotePageImages
) -> None:
    """Upsert PageMeta scan-image URLs and mirror the proofread quality onto
    Page.quality_level."""
    try:
        meta = session.exec(select(PageMeta).where(PageMeta.page_pk == page_pk)).first()
        if meta is None:
            meta = PageMeta(page_pk=page_pk)
        if images.thumbnail_url is not None:
            meta.thumb_url = images.thumbnail_url
        if images.fullsize_url is not None:
            meta.source_image_url = images.fullsize_url
        session.add(meta)

        if images.quality is not None:
            page = session.get(Page, page_pk)
            if page is not None:
                page.quality_level = images.quality
                session.add(page)

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.rollback()


def download_file_blob(
    session: Session,
    site: Site,
    page: CachedPage,
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


def _fan_out_index(ctx: ProcessContext, index_page: CachedPage) -> int:
    """Download the File: blob, parse page count, enqueue index children.

    Returns the number of child FetchRequests created.
    """
    session, req = ctx.session, ctx.request
    file_title = _index_to_file_title(req.title)
    download_file_blob(
        session, ctx.site, index_page, file_title, ctx.client, ctx.blob_root
    )

    # Prefer page_count set at upsert (from IndexPage.num_pages via
    # PywikibotClient); fall back to <pagelist> parsing for FakeWikiClient.
    page_count = index_page.page_count or parse_page_count(index_page.text or "")
    subpage_titles = ctx.client.list_index_subpage_titles(req.title)

    try:
        db_index_page = session.get(Page, index_page.pk)
        if db_index_page is not None and page_count:
            db_index_page.page_count = page_count
            session.add(db_index_page)

        basename = _index_basename(req.title)
        child_specs: list[tuple[str, FetchKind]] = []
        if page_count:
            child_specs.extend(
                (f"Page:{basename}/{n}", FetchKind.page)
                for n in range(1, page_count + 1)
            )
        child_specs.extend((title, FetchKind.single) for title in subpage_titles)

        seen_titles: set[str] = set()
        child_count = 0
        for title, kind in child_specs:
            if title in seen_titles:
                continue
            seen_titles.add(title)
            child = FetchRequest(
                site_pk=req.site_pk,
                parent_pk=req.pk,
                title=title,
                kind=kind,
                depth=0,
            )
            session.add(child)
            child_count += 1

        session.commit()
        return child_count
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


def parse_page_count(body: str) -> int | None:
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
