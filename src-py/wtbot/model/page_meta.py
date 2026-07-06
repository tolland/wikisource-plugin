import re
from enum import Enum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

"""Per-role attribute extensions for Page.

Page stays one table (whole-work scans are a core use case) and keeps the
*fetched remote state*. Everything else — curated values a user sets, or
locally derived values with their own lifecycle — lives in these side
tables, one row per page, keyed by page_pk. Adding a new role-specific
attribute means a column here, not another nullable column on Page.

These tables store values only. Whether/how they surface to the client
(extra VFS stat metadata vs. a separate preview/approval endpoint) is a
client-contract decision deferred until those tool windows exist.
"""


def default_short_name(index_title: str) -> str:
    """Filename-safe default for [IndexMeta.short_name], derived from the
    Index title: namespace prefix and file extension stripped, separators
    collapsed to single underscores (spaced hyphens collapse to a hyphen).

    'Index:Wittgenstein - Tractatus Logico-Philosophicus, 1922.djvu'
    -> 'Wittgenstein-Tractatus_Logico-Philosophicus_1922'

    A default only — users are expected to shorten it (e.g. 'Tractatus').
    """
    _, _, base = index_title.partition(":")
    base = re.sub(r"\.[A-Za-z0-9]+$", "", base)
    base = re.sub(r"[^\w\-]+", "_", base, flags=re.ASCII)
    base = re.sub(r"_*-[-_]*", "-", base)
    base = re.sub(r"__+", "_", base)
    return base.strip("_-")


SHORT_NAME_RE = re.compile(r"^[\w\-]+$", re.ASCII)
"""Valid short_name: filename-safe on every platform and inside MediaWiki
File: titles (no spaces, slashes, colons or other reserved characters)."""


class IndexMeta(SQLModel, table=True):
    """Curated per-Index metadata.

    `short_name` seeds generated child names —
    ``File:{short_name}_page_{page}_image_{n}.jpg`` — because the full Index
    title (spaces, punctuation, extension) makes miserable filenames.

    Unique per *site*, not globally: the common scenario is a local staging
    instance synced back to upstream wikisource, so generated names must be
    collision-free within the site they will be pushed to; the same work
    staged for two sites may happily reuse one short name.
    """

    __table_args__ = (
        UniqueConstraint("site_pk", "short_name", name="uq_indexmeta_site_short"),
        UniqueConstraint("page_pk", name="uq_indexmeta_page"),
    )

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)
    site_pk: int = Field(foreign_key="site.pk", index=True)

    short_name: str
    # Room to grow: image_name_pattern, OCR region templates, ...


class PageMeta(SQLModel, table=True):
    """Per-Page: ProofreadPage metadata — the structural link to the owning
    Index: (also used by Index-namespace assets like styles.css), the
    proofread quality, and the (scan page) source-image values for showing
    the page scan and its thumbnail next to the transcription in the client.

    Remote URLs come from imageinfo/ProofreadPage at fetch time; local paths
    are filled by the (future) raster cache that extracts page N from the
    backing DjVu/PDF into blob_root.
    """

    __table_args__ = (UniqueConstraint("page_pk", name="uq_pagemeta_page"),)

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)

    # ProofreadPage structure (derived from the title / Index fan-out)
    index_title: str | None = Field(default=None, index=True)
    page_number: int | None = None
    quality_level: int | None = None  # ProofreadPage <pagequality level="N"/>, 0-4

    # Remote (from the wiki's imageinfo / ProofreadPage APIs)
    source_image_url: str | None = None  # full-size page raster
    thumb_url: str | None = None
    thumb_width: int | None = None
    thumb_height: int | None = None

    # Local (raster cache under blob_root; None until extracted)
    raster_path: str | None = None
    thumb_path: str | None = None


class FileOrigin(str, Enum):
    remote = "remote"  # fetched from the wiki
    paste = "paste"  # screenshot pasted in the editor
    ocr = "ocr"  # produced by a templated-region OCR run


class FileMeta(SQLModel, table=True):
    """Provenance for File: pages.

    For images cropped out of a scan page, the crop geometry (in source
    raster pixels) records where the image came from — which is also exactly
    the input a templated-region batch OCR run iterates over, so it is
    captured from day one rather than reconstructed later.
    """

    __table_args__ = (UniqueConstraint("page_pk", name="uq_filemeta_page"),)

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)

    origin: FileOrigin = FileOrigin.remote
    source_page_pk: int | None = Field(default=None, foreign_key="page.pk")
    source_page_number: int | None = None
    crop_x: int | None = None
    crop_y: int | None = None
    crop_w: int | None = None
    crop_h: int | None = None
