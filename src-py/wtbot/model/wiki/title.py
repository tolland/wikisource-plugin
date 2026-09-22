from enum import Enum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from wtbot.model.wiki.namespace import NsRole

"""The addressable identity of a page, whether or not the wiki has one.

Named after MediaWiki's own ``Title``, and split from ``WikiPage`` for the same
reason MediaWiki splits them: a title is an address, and asking whether the
wiki holds anything at it is a separate question with a separate answer.

Everything local hangs off a Title -- the edit journal, commits, page and
revision correspondence, proofread metadata, annotations -- because all of
those are things *we* know about an address, and none of them require the wiki
to have a page there. A paginated ``Page:`` nobody has transcribed still has a
scan, a default body, a page number and an index; a user can open it, edit it
and save it. None of that is a degenerate case of an existing page.

``(site_pk, title)`` is the natural key. ``pageid`` is wiki-local and not
comparable across independently-running instances, which is exactly why this
cannot be ``pageid INTEGER PRIMARY KEY`` -- and why it lives on ``WikiPage``.
"""


class FetchState(str, Enum):
    unfetched = "unfetched"
    pending = "pending"
    fetching = "fetching"
    done = "done"
    error = "error"


class Title(SQLModel, table=True):
    """One (site, title) address -- mainspace, Index:, Page:, Book:, anything.

    One table, not three: "search/replace across the whole work" is a core use
    case and wants a single scan. ``namespace_role`` discriminates shape.
    """

    __table_args__ = (UniqueConstraint("site_pk", "title", name="uq_title_site_title"),)

    pk: int | None = Field(default=None, primary_key=True)
    site_pk: int = Field(foreign_key="site.pk")

    title: str  # full title incl. namespace prefix, e.g. 'Page:Foo.djvu/171'
    namespace_role: NsRole = NsRole.other

    # -- local state ---------------------------------------------------------
    # Deliberately the only mutable-by-us columns here. The wiki's own facts
    # are in WikiPage; content is in Revision/Content. Nothing on this row is
    # a cached copy of anything remote, so nothing on it can go stale.
    dirty: bool = Field(default=False, index=True)

    # -- fetch coverage ------------------------------------------------------
    # Facts about *our queries*, not about the page. `_is_placeholder` used to
    # AND one of these against "has no revision" precisely because the two
    # belonged to different objects; now they do.
    fetch_status: FetchState = FetchState.unfetched
    fetch_error: str | None = None

    history_complete_from_revid: int | None = None
    """Oldest revid from which our Revision rows are known to be *contiguous*.

    None means we hold no guaranteed-complete range, only whatever individual
    revisions happened to be fetched. Without this, a base search cannot tell
    "the histories diverge here" from "this is merely the oldest row we hold"."""

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return f"Title(pk={self.pk}, title={self.title!r})"
