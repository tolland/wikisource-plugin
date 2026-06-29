from datetime import datetime

from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow


class EditJournal(SQLModel, table=True):
    """Local transaction log of IDE saves, kept distinct from the cached remote
    body. Every VFS write appends a row (and flips Page.dirty); a commit reads
    the uncommitted rows, pushes via pywikibot, and marks them committed. This
    is what keeps "save in the IDE" cheap/offline and separate from "push to the
    wiki"."""

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)

    base_revid: int | None = None  # remote revid this edit started from
    body: str  # the saved buffer
    comment: str | None = None  # edit summary (usually filled at commit time)

    saved_at: datetime = Field(default_factory=utcnow)
    committed: bool = Field(default=False, index=True)
