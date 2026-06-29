from datetime import datetime

from sqlmodel import Field, SQLModel


class FileBlob(SQLModel, table=True):
    """Stat-like record for a downloaded File: binary.

    Tracks what pywikibot's FileInfo / MediaWiki imageinfo API returns for a
    specific file revision, plus the local path of the downloaded blob.  The
    VFS uses this to answer stat/HEAD requests without re-reading the file.

    ``file_sha1`` is the SHA1 of the binary payload -- distinct from the
    wikitext revision sha1 on Page and the correct cache-key for the blob.
    A new revision of the file gets a new row (or an upsert of the fields).
    """

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)

    # MediaWiki imageinfo fields (pywikibot FileInfo attributes)
    file_sha1: str | None = None  # SHA1 of the binary (not the wikitext rev)
    size: int | None = None  # bytes
    mime: str | None = None  # e.g. 'image/vnd.djvu', 'application/pdf'
    url: str | None = None  # canonical download URL on the source wiki
    upload_timestamp: datetime | None = None
    uploader: str | None = None
    upload_comment: str | None = None
    page_count: int | None = None  # pages in a multi-page format (DjVu, PDF)
    width: int | None = None  # pixels (raster images only)
    height: int | None = None  # pixels (raster images only)

    # Local filesystem state
    local_path: str | None = None  # absolute path of the downloaded blob
    downloaded_at: datetime | None = None
