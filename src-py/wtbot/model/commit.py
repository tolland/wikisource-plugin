from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow


class CommitStatus(str, Enum):
    pending = "pending"
    success = "success"
    conflict = "conflict"
    error = "error"


class Commit(SQLModel, table=True):
    """Outbound log -- one row per attempted push back to the wiki. Kept as a log
    (not an in-place overwrite of Page.revid) so a rejected edit-conflict attempt
    is visible and retriable rather than silently lost, and the IDE can show
    "this save failed, here's why" after the fact."""

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)

    base_revid: int | None = None  # revid the edit was based on; None = page creation
    submitted_body: str
    comment: str | None = None

    status: CommitStatus = Field(default=CommitStatus.pending, index=True)
    result_revid: int | None = None  # new revid on success
    error_message: str | None = None

    created_at: datetime = Field(default_factory=utcnow)
