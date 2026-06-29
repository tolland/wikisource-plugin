from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow


class FetchKind(str, Enum):
    single = "single"  # just this title, no expansion
    index = "index"  # Index + its File + all its Pages
    page = "page"  # a single Page: (usually a fan-out child)
    transclusion = "transclusion"  # + mainspace works transcluding those Pages


class FetchStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    error = "error"
    cancelled = "cancelled"


class FetchRequest(SQLModel, table=True):
    """The cache-fill queue (out-of-band, "git checkout" path). The plugin
    INSERTs; the pywikibot worker claims pending rows, updates status/progress,
    and fans out children for an Index (parent_pk) so the plugin can watch
    aggregate progress on the one request it submitted."""

    pk: int | None = Field(default=None, primary_key=True)
    site_pk: int = Field(foreign_key="site.pk")
    parent_pk: int | None = Field(default=None, foreign_key="fetchrequest.pk")

    title: str  # 'Index:...djvu', 'Page:...djvu/3', or a mainspace title
    kind: FetchKind = FetchKind.index
    depth: int = 0  # 0 = this title only; >0 = expand associated assets

    status: FetchStatus = Field(default=FetchStatus.pending, index=True)
    priority: int = 0  # higher = sooner ("open this now" jumps the queue)
    progress_done: int = 0
    progress_total: int | None = None
    error_message: str | None = None

    requested_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
