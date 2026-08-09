from datetime import datetime
from enum import StrEnum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

"""Scan annotations: bounding boxes drawn over a proofread page's scan image.

One row per box, in scan-pixel coordinates (the coordinate space of the
full-resolution scan, independent of any on-screen zoom). ``annotation_id``
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


class ScanAnnotation(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "page_pk", "annotation_id", name="uq_scan_annotation_page_annotation"
        ),
    )

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)
    annotation_id: str = Field(index=True)

    x: float
    y: float
    width: float
    height: float

    label: str | None = None
    category: AnnotationCategory | None = None

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
