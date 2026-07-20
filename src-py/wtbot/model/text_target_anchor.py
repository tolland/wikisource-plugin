from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

"""Anchors into text documents that are targets for processed text.

A TextTargetAnchor marks a range of a text document (today: a proofread
page's transcription) as the destination for text produced elsewhere — OCR
of a scan region, or any other source of processed text. It carries no
geometry: the scan-side bounding box lives in wtbot.model.scan_annotation,
and ``annotation_id`` is the join key between the two. The two sides are
managed independently — an anchor may be created before its box (mark the
text first, draw the region later) and vice versa.

Offsets are character offsets into the transcription text as the client
editor presents it as of ``anchor_revid`` — for ProofreadPage pages that is
the *body* section (header/footer excluded); for unstructured buffers, the
whole text. The client re-anchors open documents with RangeMarkers and
writes refreshed offsets back. A row whose anchor_revid no longer matches
the page is *stale*, which the client must surface rather than trust.
"""


class TextTargetAnchor(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "page_pk", "annotation_id", name="uq_text_target_anchor_page_annotation"
        ),
    )

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)
    annotation_id: str = Field(index=True)

    # text_start == text_end is an insertion point; < is a replace range.
    text_start: int
    text_end: int
    anchor_revid: int | None = None

    updated_at: datetime = Field(default_factory=datetime.now)
