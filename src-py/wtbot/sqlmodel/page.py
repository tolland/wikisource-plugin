from datetime import datetime
from enum import Enum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from wtbot.sqlmodel.namespace import NsRole


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

    __table_args__ = (
        UniqueConstraint("site_pk", "title", name="uq_page_site_title"),
    )

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
    sha1: str | None = None

    # Local editing state
    body: str | None = None  # raw wikitext, null until fetched
    local_modified_at: datetime | None = None  # when THIS row last changed locally;
    # deliberately distinct from remote_timestamp -- conflating them is a known bug class.
    dirty: bool = Field(default=False, index=True)

    # Page-role specific (null otherwise)
    index_title: str | None = Field(default=None, index=True)
    page_number: int | None = None
    quality_level: int | None = None  # ProofreadPage <pagequality level="N"/>, 0-4

    # Index-role specific (null otherwise)
    file_ref: str | None = None  # path of the backing PDF/DjVu blob on disk
    page_count: int | None = None  # total pages per the Index <pagelist>

    fetch_status: FetchState = FetchState.unfetched
    fetch_error: str | None = None

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return f"Page(pk={self.pk}, title={self.title!r})"
