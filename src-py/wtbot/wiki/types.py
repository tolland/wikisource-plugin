from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


class PageNotFound(Exception):
    """Raised by a WikiClient when a title does not exist on the wiki."""


@dataclass(frozen=True)
class RemoteFileInfo:
    """Binary-file metadata from MediaWiki's imageinfo API (pywikibot FileInfo).

    ``file_sha1`` is the SHA1 of the actual binary, distinct from the wikitext
    revision SHA1 on RemotePage. This is the correct cache-key for the blob and
    the VFS stat oracle.
    """

    title: str
    file_sha1: str
    size: int                     # bytes of the binary file
    mime: str                     # e.g. 'image/vnd.djvu', 'application/pdf'
    url: str                      # canonical download URL on the wiki

    upload_timestamp: datetime | None = None
    uploader: str | None = None
    upload_comment: str | None = None
    page_count: int | None = None  # for multi-page formats (DjVu, PDF)
    width: int | None = None       # pixels (images only)
    height: int | None = None      # pixels (images only)


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
