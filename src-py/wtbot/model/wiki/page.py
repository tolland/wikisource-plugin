from datetime import datetime

from sqlmodel import Field, Relationship, SQLModel

from wtbot.model.wiki.title import Title


class Page(SQLModel, table=True):
    """A page the wiki holds, at a Title -- mainspace, Index:, Page:, Book:,
    anything. A row exists iff the wiki holds the page (step 3 of the
    Title/WikiPage split, docs/design/pages-and-existence.md); everything about
    the address, including its name, is the Title's.

    One table, not three: "search/replace across the whole work" is a core use
    case and wants a single scan. The content model determines supported
    operations; namespace identity and capabilities come from the per-site
    namespace map. pageid/revid are wiki-local and not comparable across
    independently-running instances -- which is exactly why this can't be
    ``pageid INTEGER PRIMARY KEY``.
    """

    pk: int | None = Field(default=None, primary_key=True, foreign_key="title.pk")
    """Shared with ``Title``: a page is at exactly one title and takes its pk.
    Set it from the Title when constructing a Page (or set ``address``, and the
    flush copies the Title's pk across)."""

    address: Title = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    """The Title this page is at -- its name, and what belongs to the address
    (namespace, fetch status, dirty) rather than to the page the wiki holds.
    Loaded with the page, so a listing of pages costs one extra query, not one
    per page."""

    site_pk: int = Field(foreign_key="site.pk")
    """The title's site, repeated. Written once, from the Title."""

    # namespace_key, dirty, fetch_status and local_modified_at belong to the
    # address and live on Title (see wtbot.model.wiki.title).
    content_model: str  # remote contentmodel ('proofread-index', ...)

    # Remote identity / revision state -- this IS the conflict token. revid +
    # remote_timestamp are sent back as basetimestamp on save; a mismatch on save
    # is a real edit conflict, not a bug. sha1 is MediaWiki's content hash and is
    # also the cross-wiki "same content" oracle (see RemoteLink, future).
    # Required: a Page row exists only where the wiki holds the page, and a held
    # page has all three (step 3 of the Title/WikiPage split).
    pageid: int
    revid: int
    remote_timestamp: datetime
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
    text: str

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
        return f"Page(pk={self.pk}, revid={self.revid})"
