from datetime import datetime

from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow


class EditJournal(SQLModel, table=True):
    """Local transaction log of IDE saves, kept distinct from the cached remote
    body. Every VFS write appends a row (and flips Title.dirty); a commit reads
    the uncommitted rows, pushes via pywikibot, and marks them committed. This
    is what keeps "save in the IDE" cheap/offline and separate from "push to the
    wiki"."""

    pk: int | None = Field(default=None, primary_key=True)
    title_pk: int = Field(foreign_key="title.pk", index=True)
    """The address saved to. A Title, not a Page: a save needs nothing on the
    wiki, and the first save of an untranscribed page is the ordinary case."""

    base_revid: int | None = None  # remote revid this edit started from
    body: str  # the saved buffer
    comment: str | None = None  # edit summary (usually filled at commit time)

    saved_at: datetime = Field(default_factory=utcnow)
    committed: bool = Field(default=False, index=True)
