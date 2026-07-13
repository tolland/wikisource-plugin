from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

"""Text anchors for scan annotations.

The geometry of an annotation lives in the per-page SVG document under
blob_root (see wtbot.annotation_svg) — portable, Inkscape/browser-openable.
What SVG holds badly is the *relation to the transcription text*, so that
half lives here: one row per linked annotation, joined by the SVG element's
id. An annotation with no row is an unlinked box.

Offsets are plain character offsets into Page.text as of ``anchor_revid``
(plus local edits — the client re-anchors open documents with RangeMarkers
and writes refreshed offsets back). A row whose anchor_revid no longer
matches the page is *stale*, which the client must surface rather than
trust; a row whose annotation_id has no SVG element (e.g. the rect was
deleted in Inkscape) is *dangling*, which the API reports on import.
"""


class AnnotationAnchor(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("page_pk", "annotation_id", name="uq_anchor_page_annotation"),
    )

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)
    annotation_id: str = Field(index=True)

    # text_start == text_end is an insertion point; < is a replace range.
    text_start: int
    text_end: int
    anchor_revid: int | None = None

    updated_at: datetime = Field(default_factory=datetime.now)
