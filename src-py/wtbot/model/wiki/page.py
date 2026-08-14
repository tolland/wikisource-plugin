from datetime import datetime
from enum import Enum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from wtbot.model.wiki.namespace import NsRole


class FetchState(str, Enum):
    unfetched = "unfetched"
    pending = "pending"
    fetching = "fetching"
    done = "done"
    error = "error"


class Page(SQLModel, table=True):
    """One (site, title) object -- mainspace, Index:, Page:, Book:, anything.
    One table, not three: "search/replace across the whole work" is a core use
    case and wants a single scan. The namespace role discriminates shape;
    role-specific columns are nullable and only meaningful for their role.

    (site_pk, title) is the natural key. pageid/revid are wiki-local and not
    comparable across independently-running instances -- which is exactly why
    this can't be ``pageid INTEGER PRIMARY KEY``.
    """

    __table_args__ = (UniqueConstraint("site_pk", "title", name="uq_page_site_title"),)

    pk: int | None = Field(default=None, primary_key=True)
    site_pk: int = Field(foreign_key="site.pk")

    title: str  # full title incl. namespace prefix, e.g. 'Page:Foo.djvu/171'
    namespace_role: NsRole = NsRole.other
    namespace_key: int | None = None  # site-local numeric ns id, informational
    content_model: str | None = None  # remote contentmodel ('proofread-index', ...)

    # Remote identity / revision state -- this IS the conflict token. revid +
    # remote_timestamp are sent back as basetimestamp on save; a mismatch on save
    # is a real edit conflict, not a bug. sha1 is MediaWiki's content hash and is
    # also the cross-wiki "same content" oracle (see RemoteLink, future).
    pageid: int | None = None
    revid: int | None = None
    remote_timestamp: datetime | None = None
    contributor: str | None = None
    comment: str | None = None
    # `sha1` used to live here. It was dropped rather than kept: nothing read
    # it, and it held the *remote* hash in *hex* while Content.content_sha1
    # holds *ours* in *base-36* -- the same name for a different quantity in a
    # different encoding. Read hashes off the slot's Content instead.

    # Local editing state
    # `text` is the full raw content as returned by the MediaWiki API
    # (page.text in pywikibot). Consumers that need a content-model-specific
    # view should parse this field with the page's content_model.
    text: str | None = None
    local_modified_at: datetime | None = None  # when THIS row last changed locally;
    # deliberately distinct from remote_timestamp -- conflating them is a known bug class.
    dirty: bool = Field(default=False, index=True)

    fetch_status: FetchState = FetchState.unfetched
    fetch_error: str | None = None

    # --- revision store (see wtbot.model.revision) -------------------------
    # The columns above stay as the head denormalisation -- mirroring
    # MediaWiki's own page_latest/page_len rather than deviating from it -- and
    # remain the only thing most callers read. These two describe the Revision
    # rows behind them.
    latest_revision_pk: int | None = None
    """The head Revision row, once fetched -- our analogue of ``page_latest``.

    Deliberately *not* a declared foreign key. Revision already points at Page,
    so declaring the reverse creates a cycle SQLAlchemy cannot order ("there are
    unresolvable cycles between tables page, revision"), and under
    ``PRAGMA foreign_keys=ON`` it would also block deleting a head revision.
    MediaWiki's own DDL declares no foreign keys either -- ``page_latest`` and
    ``rev_page`` are plain integers -- so this is the faithful mirror, not a
    shortcut."""

    history_complete_from_revid: int | None = None
    """Oldest revid from which our Revision rows are known to be *contiguous*.

    None means we hold no guaranteed-complete range, only whatever individual
    revisions happened to be fetched. Without this, a base search cannot tell
    "the histories diverge here" from "this is merely the oldest row we hold" --
    the same known-absent/unknown hazard placeholders already have at page
    level."""

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return f"Page(pk={self.pk}, title={self.title!r})"
