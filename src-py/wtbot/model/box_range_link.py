from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

"""Explicit link from a scan bounding box to a text target range.

A BoxRangeLink says "the content of this box is destined for that text
range": ``box_annotation_id`` names a row in wtbot.model.scan_annotation
and ``range_annotation_id`` a row in wtbot.model.text_target_anchor, both
on the same page. It replaces the earlier implicit convention of a box and
its anchor *sharing* one annotation id — boxes and ranges are created
independently and linked (and re-linked) after the fact, so the join must
be its own row rather than an id pun.

A box sends its content to at most one range (unique per
``box_annotation_id``); nothing stops several boxes from targeting the
same range, which the client may render as it sees fit.

A link is only meaningful while both endpoints exist: deleting the box or
deleting the range deletes the link (enforced in wtbot.api.annotations, as
neither endpoint table declares real foreign keys to the other).
"""


class BoxRangeLink(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("page_pk", "box_annotation_id", name="uq_box_range_link_box"),
    )

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)

    box_annotation_id: str = Field(index=True)
    range_annotation_id: str = Field(index=True)

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
