import re
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func
from sqlmodel import Session, select

from wtbot.log.fetch_log import activity, fetch_stage
from wtbot.model import FetchState, FileBlob, Page, Site
from wtbot.model.fetch.fetch_request import FetchKind, FetchRequest, FetchStatus
from wtbot.model.wiki.namespace import FILE_NAMESPACE_KEY
from wtbot.model.wikisource.proofread_page_meta import ProofreadPageMeta
from wtbot.timeutil import utcnow
from wtbot.title_store import ensure_title
from wtbot.vfs.store import PageStore
from wtbot.wiki.client import WikiClient
from wtbot.wiki.wiki_types import PageNotFound, RemotePage, RemotePageImages

"""Per-page-type fetch processing.

The worker fetches a RemotePage and upserts the common Page fields; what
happens *around* that differs by page type. Each type gets a processor
class implementing [PageProcessor]:

  ProofreadPageProcessor   Page:  — resolve Index key/page number,
                           pull the scan image URLs + quality
                           (prop=imageforpage) into ProofreadPageMeta
  ProofreadIndexProcessor  Index: — IndexMeta.page_count, File: blob, fan-out
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
    revisions: int = 1


@dataclass(frozen=True)
class CachedPage:
    """Detached snapshot of the upserted Page row."""

    pk: int
    title: str
    content_model: str | None
    text: str | None


@dataclass(frozen=True)
class ProcessContext:
    session: Session
    site: Site
    client: WikiClient
    request: ClaimedFetchRequest
    blob_root: Path | None
    #: Scan-image metadata already fetched in bulk during this drain, by title.
    #: An Index fan-out knows every child title before any child is processed,
    #: so it asks once for fifty of them instead of once per child -- the
    #: second request per page that measurement showed doubling the budget. A
    #: present key means "already asked", including when the answer was
    #: nothing; a missing key falls back to a per-page request, which is what
    #: happens when a child is drained in a later run than its fan-out.
    image_cache: dict[str, RemotePageImages | None] | None = None


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
    def postprocess(
        self, ctx: ProcessContext, cached: CachedPage, remote: RemotePage
    ) -> ProcessOutcome:
        images = _page_images(ctx, cached.title)
        if images is not None:
            _store_page_images(ctx.session, cached.pk, images)
        return _DONE


def proofread_index_identity(title: str) -> tuple[str, int] | None:
    """Derive the conventional owning Index title and scan position."""
    after_ns = title.split(":", 1)[-1]
    base, _, num = after_ns.rpartition("/")
    if not base or not num.isdigit():
        return None
    return f"Index:{base}", int(num)


def _page_images(ctx: ProcessContext, title: str) -> RemotePageImages | None:
    """Scan-image metadata for one page, from the drain's bulk prefetch when
    the fan-out took it, else asked for directly."""
    if ctx.image_cache is not None and title in ctx.image_cache:
        activity("image_cache hit title=%r", title)
        return ctx.image_cache[title]
    with fetch_stage("page_images"):
        return ctx.client.get_page_images(title)


def _prefetch_page_images(ctx: ProcessContext, titles: list[str]) -> None:
    """Ask once for every child's scan image, before the children are fetched.

    Fail-soft like the per-page call it replaces: on any error the cache stays
    empty and each child asks for itself, which costs requests but loses
    nothing.
    """
    if ctx.image_cache is None or not titles:
        return
    wanted = [title for title in titles if title not in ctx.image_cache]
    if not wanted:
        return
    try:
        with fetch_stage("bulk_page_images", f"titles={len(wanted)}"):
            found = ctx.client.get_page_images_bulk(wanted)
    except Exception:  # noqa: BLE001 - enrichment, never fatal
        activity(
            "bulk image prefetch failed titles=%d; falling back to per-page calls",
            len(wanted),
        )
        return
    for title in wanted:
        # Absent titles are cached as None: "asked, nothing there" must not
        # send every one of them back to ask again individually.
        ctx.image_cache[title] = found.get(title)


class ProofreadIndexProcessor(PageProcessor):
    def postprocess(
        self, ctx: ProcessContext, cached: CachedPage, remote: RemotePage
    ) -> ProcessOutcome:
        if ctx.request.depth <= 0:
            # No fan-out, but still record page_count from the cheap sources
            # (IndexPage.num_pages, or the <pagelist> in the body) so a
            # depth-0 index fetch populates it just like the old enrich did.
            _record_index_page_count(
                ctx, cached, remote.page_count or parse_page_count(cached.text or "")
            )
            return _DONE
        child_count = _fan_out_index(ctx, cached, remote)
        return ProcessOutcome(
            status=FetchStatus.in_progress if child_count > 0 else FetchStatus.done,
            progress_total=1 + child_count,
            progress_done=1,
        )


class IndexAssetProcessor(PageProcessor):
    """Index subpages are related by ordinary MediaWiki subpage semantics."""


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
    if remote.namespace_key == FILE_NAMESPACE_KEY:
        return _FILE
    if remote.content_model == "proofread-index":
        return _PROOFREAD_INDEX
    if remote.content_model == "proofread-page":
        return _PROOFREAD_PAGE
    return _DEFAULT


# ---------------------------------------------------------------------------
# Shared side-effect helpers
# ---------------------------------------------------------------------------


def _record_index_page_count(
    ctx: ProcessContext, cached: CachedPage, page_count: int | None
) -> None:
    """Ensure the Index's IndexMeta row exists and record [page_count] on it,
    in its own short transaction (postprocess runs outside the upsert)."""
    if not page_count:
        return
    session = ctx.session
    try:
        db_index_page = session.get(Page, cached.pk)
        if db_index_page is None:
            return
        store = PageStore(session)
        store.set_index_page_count(store.ensure_index_meta(db_index_page), page_count)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.rollback()


def _store_page_images(
    session: Session, page_pk: int, images: RemotePageImages
) -> None:
    """Upsert ProofreadPageMeta scan-image URLs and proofread quality."""
    try:
        meta = session.exec(
            select(ProofreadPageMeta).where(ProofreadPageMeta.title_pk == page_pk)
        ).first()
        if meta is None:
            # A proofread fetch creates structural metadata during its page
            # upsert, before image enrichment runs.
            return
        if images.thumbnail_url is not None:
            meta.thumb_url = images.thumbnail_url
            meta.thumb_width = images.size
        if images.fullsize_url is not None:
            meta.source_image_url = images.fullsize_url
        if images.quality is not None:
            meta.quality_level = images.quality
        session.add(meta)

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
    """Fetch imageinfo + download binary for its owning File: page."""
    if page.title != file_title:
        raise ValueError("the blob owner must be the fetched File: page")
    dest = _blob_path(blob_root, site, file_title)
    try:
        with fetch_stage("file_info", f"title={file_title!r}"):
            info = client.get_file_info(file_title)
        with fetch_stage("file_download", f"title={file_title!r} bytes={info.size}"):
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
    ctx: ProcessContext, index_page: CachedPage, remote: RemotePage
) -> int:
    """Enqueue the backing File:, enumerate the index pagination, enqueue
    fetches for pages that exist remotely and create placeholder stub rows
    for the ones that do not. Placeholders are enriched from the wiki up
    front (scan image URLs + prepopulated OCR body) so transcription can
    start on them straight away.

    Pagination comes from list=proofreadpagesinindex when available:
    authoritative titles, and missing pages known up front — no fetch
    request is wasted learning PageNotFound one page at a time. Wikis
    without the API fall back to page_count interpolation, where every slot
    is enqueued and existence is discovered the slow way.

    Returns the number of child FetchRequests created.
    """
    session, req = ctx.session, ctx.request

    file_title = _index_to_file_title(req.title)

    store = PageStore(session)

    db_index_page = session.get(Page, index_page.pk)

    index_meta = (
        store.ensure_index_meta(db_index_page) if db_index_page is not None else None
    )

    # Prefer page_count from IndexPage.num_pages (via PywikibotClient); fall
    # back to <pagelist> parsing for FakeWikiClient.
    page_count = remote.page_count or parse_page_count(index_page.text or "")
    with fetch_stage("index_subpages"):
        subpage_titles = ctx.client.list_index_subpage_titles(req.title)
    with fetch_stage("index_pagination"):
        entries = ctx.client.list_index_pages(req.title)

    child_specs: list[tuple[str, FetchKind]] = [(file_title, FetchKind.single)]
    stub_specs: list[tuple[str, int]] = []  # (title, page_number)
    if entries is not None:
        page_count = page_count or len(entries)
        for entry in entries:
            if entry.pageid is not None:
                child_specs.append((entry.title, FetchKind.page))
            else:
                stub_specs.append((entry.title, entry.page_offset))
    elif page_count:
        basename = _index_basename(req.title)
        child_specs.extend(
            (f"Page:{basename}/{n}", FetchKind.page) for n in range(1, page_count + 1)
        )
    child_specs.extend((title, FetchKind.single) for title in subpage_titles)

    activity(
        "index fan-out children=%d placeholders=%d", len(child_specs), len(stub_specs)
    )

    # Network calls, so before the fan-out transaction opens.
    enrichments = _gather_placeholder_enrichment(
        session, ctx.client, req.site_pk, stub_specs
    )
    # One question for every child's scan image, asked here because this is
    # the only point that knows all of them at once. Each child would
    # otherwise ask for itself when it is fetched -- the second request per
    # page that a measured fan-out showed doubling the per-page budget.
    _prefetch_page_images(
        ctx, [title for title, kind in child_specs if kind is FetchKind.page]
    )

    try:
        if index_meta is not None and page_count:
            store.set_index_page_count(index_meta, page_count)

        for title, page_number in stub_specs:
            _ensure_placeholder_page(
                session,
                req.site_pk,
                req.title,
                title,
                page_number,
                enrichment=enrichments.get(title),
            )

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
                # Children inherit the history depth: an anchor search over a
                # work needs the same view of every page in it, and a fan-out
                # that fetched only the index deeply would leave every child
                # reporting `history_exhausted`.
                revisions=req.revisions,
            )
            session.add(child)
            child_count += 1

        session.commit()
        activity(
            "fan-out stored children=%d placeholders=%d", child_count, len(stub_specs)
        )
        return child_count
    except Exception:
        session.rollback()
        raise
    finally:
        session.rollback()


@dataclass(frozen=True)
class PlaceholderEnrichment:
    """What the wiki offers for a Page: that does not exist yet: the scan
    reference image (imageforpage works off the Index's File:, created page
    or not) and the body ProofreadPage's own editor would prepopulate (the
    OCR text layer, prop=defaultcontentforpage)."""

    images: RemotePageImages | None = None
    default_body: str | None = None


def _gather_placeholder_enrichment(
    session: Session,
    client: WikiClient,
    site_pk: int,
    stub_specs: list[tuple[str, int]],
) -> dict[str, PlaceholderEnrichment]:
    """Fetch scan-image URLs + the prepopulated OCR body for each placeholder
    slot. Skips stubs a previous fan-out already enriched, so a refresh of a
    large index costs no per-stub round trips."""
    titles = [title for title, _ in stub_specs]
    if not titles:
        return {}
    try:
        rows = session.exec(
            select(Page, ProofreadPageMeta)
            .join(
                ProofreadPageMeta,
                ProofreadPageMeta.title_pk == Page.pk,
                isouter=True,
            )
            .where(Page.site_pk == site_pk, Page.title.in_(titles))
        ).all()
    finally:
        session.rollback()
    enriched = {
        page.title
        for page, meta in rows
        if meta is not None
        and meta.default_body is not None
        and (meta.thumb_url is not None or meta.source_image_url is not None)
    }
    wanted = [title for title in titles if title not in enriched]
    activity(
        "placeholder enrichment total=%d cached=%d remaining=%d",
        len(titles),
        len(enriched),
        len(wanted),
    )
    result: dict[str, PlaceholderEnrichment] = {}
    for position, title in enumerate(wanted, start=1):
        detail = f"page={position}/{len(wanted)} title={title!r}"
        with fetch_stage("placeholder_images", detail):
            images = client.get_page_images(title)
        with fetch_stage("placeholder_default_content", detail):
            default_body = client.get_default_page_content(title)
        result[title] = PlaceholderEnrichment(images=images, default_body=default_body)
    return result


def _apply_placeholder_enrichment(
    meta: ProofreadPageMeta, enrichment: PlaceholderEnrichment
) -> None:
    """Fill only fields still unset — the stub may carry values from an
    earlier fan-out or a partial enrichment."""
    images = enrichment.images
    if images is not None:
        if meta.thumb_url is None and images.thumbnail_url is not None:
            meta.thumb_url = images.thumbnail_url
            meta.thumb_width = images.size
        if meta.source_image_url is None and images.fullsize_url is not None:
            meta.source_image_url = images.fullsize_url
    if meta.default_body is None and enrichment.default_body is not None:
        meta.default_body = enrichment.default_body


def _ensure_placeholder_page(
    session: Session,
    site_pk: int,
    index_title: str,
    title: str,
    page_number: int,
    enrichment: PlaceholderEnrichment | None = None,
) -> None:
    """Create the local stub row for a proofread page that does not exist on
    the wiki yet — the same provisional-Page shape as a pasted upload:
    pageid/revid None means "exists locally only". Everything downstream
    (listing, stat, editing, commit-as-create) then works with no special
    cases. Never clobbers an existing row: the user may already have edits
    journalled against a stub from an earlier fan-out — an existing stub only
    gains enrichment fields it is still missing."""
    existing = session.exec(
        select(Page).where(Page.site_pk == site_pk, Page.title == title)
    ).first()
    if existing is not None:
        meta = session.exec(
            select(ProofreadPageMeta).where(ProofreadPageMeta.title_pk == existing.pk)
        ).first()
        if meta is None:
            index_page = ensure_index_page(session, site_pk, index_title)
            meta = ProofreadPageMeta(
                title_pk=existing.pk,
                index_title_pk=index_page.pk,
                page_number=page_number,
            )
        else:
            meta.page_number = page_number
        if existing.revid is None and enrichment is not None:
            _apply_placeholder_enrichment(meta, enrichment)
        session.add(meta)
        return
    # The fan-out knows its children are proofread pages before any of them is
    # fetched; that guess is the title's to hold (see Title.expected_content_model).
    title_row = ensure_title(
        session,
        site_pk=site_pk,
        title=title,
        expected_content_model="proofread-page",
    )
    page = Page(
        pk=title_row.pk,
        site_pk=site_pk,
        title=title,
        content_model="proofread-page",
    )
    # We *know* the remote state: absent. The fetch is complete.
    title_row.fetch_status = FetchState.done
    session.add(page)
    session.flush()
    index_page = ensure_index_page(session, site_pk, index_title)
    meta = ProofreadPageMeta(
        title_pk=page.pk,
        index_title_pk=index_page.pk,
        page_number=page_number,
    )
    if enrichment is not None:
        _apply_placeholder_enrichment(meta, enrichment)
    session.add(meta)


def ensure_index_page(session: Session, site_pk: int, title: str) -> Page:
    """Return the keyed Index identity, creating an unfetched placeholder."""
    canonical = title.replace("_", " ")
    index = session.exec(
        select(Page).where(
            Page.site_pk == site_pk,
            func.replace(Page.title, "_", " ") == canonical,
        )
    ).first()
    if index is not None:
        if index.content_model != "proofread-index":
            raise RuntimeError(
                f"owning Index title {title!r} resolves to non-Index page {index.pk}"
            )
        return index
    # Named as the owning Index of a proofread page, so expected to be one.
    title_row = ensure_title(
        session,
        site_pk=site_pk,
        title=title,
        expected_content_model="proofread-index",
    )
    index = Page(
        pk=title_row.pk,
        site_pk=site_pk,
        title=title,
        content_model="proofread-index",
    )
    session.add(index)
    session.flush()
    return index


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
