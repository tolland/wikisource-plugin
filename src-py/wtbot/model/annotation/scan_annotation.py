from datetime import datetime
from enum import StrEnum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow

"""Scan annotations: bounding boxes drawn over a proofread page's scan image.

One row per box, in normalized full-page coordinates (fractions from 0 to 1,
independent of the raster resolution and on-screen zoom). ``annotation_id``
is the client-generated stable identity that outlives geometry changes — it
is the join key to everything outside this table, in particular the text
anchors (see wtbot.model.text_target_anchor), which are managed separately.

``category`` classifies the region for the OCR pipeline: when page images
are cut into subsections and sent to OCR, the category decides what a box
contributes (a ``body`` or ``paragraph`` box is transcribed, ``header``/
``footer`` route to the page header/footer fields, ``ignore`` is skipped).
"""


class AnnotationCategory(StrEnum):
    header = "header"
    footer = "footer"
    body = "body"
    paragraph = "paragraph"
    section = "section"
    ignore = "ignore"
    equation = "equation"
    unknown = "unknown"


class ScanAnnotation(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "title_pk", "annotation_id", name="uq_scan_annotation_page_annotation"
        ),
    )

    pk: int | None = Field(default=None, primary_key=True)
    title_pk: int = Field(foreign_key="title.pk", index=True)
    annotation_id: str = Field(index=True)

    normalized_x: float
    normalized_y: float
    normalized_width: float
    normalized_height: float

    label: str | None = None
    category: AnnotationCategory = AnnotationCategory.unknown

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
