from dataclasses import dataclass
from datetime import datetime


class PageNotFound(Exception):
    """Raised by a WikiClient when a title does not exist on the wiki."""


class EditConflict(Exception):
    """Raised by WikiClient.save_page when the page changed remotely since
    base_revid -- the edit was not applied."""

    def __init__(self, title: str, base_revid: int, current_revid: int | None):
        super().__init__(
            f"edit conflict on {title}: based on revid {base_revid}, "
            f"remote is now {current_revid}"
        )
        self.title = title
        self.base_revid = base_revid
        self.current_revid = current_revid


@dataclass(frozen=True)
class SaveResult:
    revid: int
    timestamp: datetime | None = None


@dataclass(frozen=True)
class RenderedPreview:
    """HTML produced by the wiki's parser for an in-progress (unsaved) body via
    ``action=parse`` — the same call MediaWiki's own live preview makes.

    ``server``/``script_path`` (e.g. 'https://en.wikisource.org' + '/w') let the
    consumer link the wiki's ResourceLoader stylesheets and resolve relative
    URLs; both are None when the client has no real wiki behind it."""

    title: str
    html: str
    server: str | None = None
    script_path: str | None = None


@dataclass(frozen=True)
class RemoteFileInfo:
    """Binary-file metadata from MediaWiki's imageinfo API (pywikibot FileInfo).

    ``file_sha1`` is the SHA1 of the actual binary, distinct from the wikitext
    revision SHA1 on RemotePage. This is the correct cache-key for the blob and
    the VFS stat oracle.
    """

    title: str
    file_sha1: str
    size: int  # bytes of the binary file
    mime: str  # e.g. 'image/vnd.djvu', 'application/pdf'
    url: str  # canonical download URL on the wiki

    upload_timestamp: datetime | None = None
    uploader: str | None = None
    upload_comment: str | None = None
    page_count: int | None = None  # for multi-page formats (DjVu, PDF)
    width: int | None = None  # pixels (images only)
    height: int | None = None  # pixels (images only)


@dataclass(frozen=True)
class RemotePageImages:
    """ProofreadPage per-page scan image + proofread status, from
    ``prop=imageforpage|proofread`` (the response key is ``imagesforpage``).

    URLs are normalised to https:// (the API returns protocol-relative).
    ``size`` is the width reported by imageforpage for the served rendering.
    """

    thumbnail_url: str | None = None
    fullsize_url: str | None = None
    size: int | None = None
    filename: str | None = None
    quality: int | None = None  # ProofreadPage quality level 0-4
    quality_text: str | None = None


@dataclass(frozen=True)
class IndexPageEntry:
    """One pagination slot of a ProofreadPage index, from
    ``list=proofreadpagesinindex`` (prefix prppii). ``pageid`` is None when
    the slot has no created Page: yet — the API reports those as pageid 0,
    which is how partially transcribed works announce their gaps."""

    page_offset: int
    title: str
    pageid: int | None = None


@dataclass(frozen=True)
class RemoteChange:
    """One entry from ``list=recentchanges``: a page moved, at a time.

    Metadata only, deliberately. A recentchanges entry says a revision was
    created, **not** that the content changed -- null and touch edits produce
    entries with identical text (four such in the Canadian patent fixture). It
    is a planning signal: what to look at, never what diverged. That verdict
    comes from the content comparison after fetching.
    """

    title: str
    timestamp: datetime
    kind: str  # 'edit' | 'new' | 'log' | ...
    pageid: int | None = None
    revid: int | None = None
    old_revid: int | None = None
    namespace_key: int | None = None


@dataclass(frozen=True)
class RemotePage:
    """A plain snapshot of a wiki page, decoupled from pywikibot's Page object so
    the rest of the backend (dispatch, worker, tests) never imports pywikibot.

    ``content_model`` is what drives handling ('proofread-index',
    'proofread-page', 'wikitext', ...); ``namespace_canonical`` ('File', 'Index',
    ...) lets us apply the File: structural override (see wiki.dispatch)."""

    title: str
    namespace_key: int
    namespace_canonical: str | None
    content_model: str

    text: str

    pageid: int | None = None
    revid: int | None = None
    parentid: int | None = None
    timestamp: datetime | None = None
    user: str | None = None
    comment: str | None = None
    sha1: str | None = None
    size: int | None = None
    # ProofreadPage: total page count from IndexPage.num_pages (not <pagelist> parsing)
    page_count: int | None = None
