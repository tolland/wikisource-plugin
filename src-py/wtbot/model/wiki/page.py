from datetime import datetime

from sqlalchemy import UniqueConstraint, event, insert, select
from sqlalchemy.orm import Session
from sqlmodel import Field, Relationship, SQLModel

from wtbot.model.wiki.title import Title


class Page(SQLModel, table=True):
    """One (site, title) object -- mainspace, Index:, Page:, Book:, anything.
    One table, not three: "search/replace across the whole work" is a core use
    case and wants a single scan. The content model determines supported operations;
    namespace identity and capabilities come from the per-site namespace map.

    (site_pk, title) is the natural key. pageid/revid are wiki-local and not
    comparable across independently-running instances -- which is exactly why
    this can't be ``pageid INTEGER PRIMARY KEY``.
    """

    __table_args__ = (UniqueConstraint("site_pk", "title", name="uq_page_site_title"),)

    pk: int | None = Field(default=None, primary_key=True, foreign_key="title.pk")
    """Shared with ``Title``: every Page is a Title. See ``wtbot.model.wiki.title``.

    Leave it None when constructing a Page and the flush supplies it from the
    Title at the same (site, title), creating that Title if need be -- see
    ``_every_page_is_a_title`` below."""

    address: Title = Relationship(sa_relationship_kwargs={"lazy": "selectin"})
    """The Title this page is at -- the row holding what belongs to the address
    (namespace, fetch status, dirty) rather than to the page the wiki holds.
    Loaded with the page, so a listing of pages costs one extra query, not one
    per page. Unset on a Page not yet flushed: the flush supplies ``pk``."""

    site_pk: int = Field(foreign_key="site.pk")

    # Full title incl. namespace prefix, e.g. 'Page:Foo.djvu/171'. Mirrors
    # Title.title during the transition; written once, when both rows are made.
    title: str
    # namespace_key, dirty and fetch_status belong to the address and live on
    # Title (see wtbot.model.wiki.title).
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


_WIKITEXT = "wikitext"

# @TODO this is patching Page to Title, creating the Title if missing
# while the rest of the code base is migrated to the shared primary key
# association model relationship. Needs to be removed.


@event.listens_for(Session, "before_flush")
def _every_page_is_a_title(session: Session, _flush_context, _instances) -> None:
    """Give each new Page the pk of its Title, creating the Title if missing.

    A transition rule, not a permanent one. While ``Page`` still stands for
    "a page we know about", everything that creates one -- the fetch worker,
    the index fan-out, and dozens of test fixtures -- must also create its
    Title, and one hook here is a single place to hold that rule instead of
    a copy of it at every call site. The places that know better than a
    fallback (the fan-out knows its children are ``proofread-page``) create
    the Title themselves first; this only fills in for the rest, and its
    guess is the page's own content model or MediaWiki's ``wikitext``.

    It goes when Page stops being created directly, i.e. when it becomes the
    row a fetch writes for a title the wiki actually holds.

    Uses the session's connection rather than ORM objects: a hook may not
    flush, and the Title's pk has to exist before the Page row is inserted.
    """
    new_pages = [obj for obj in session.new if isinstance(obj, Page)]
    if not new_pages:
        return
    connection = session.connection()
    for page in new_pages:
        at_address = connection.execute(
            select(Title.pk).where(
                Title.site_pk == page.site_pk, Title.title == page.title
            )
        ).scalar()
        if page.pk is None:
            page.pk = at_address or _insert_title(connection, page)
            continue
        # An explicit pk (fixtures pin them to prove pk-independence) names
        # the Title as well; it must not contradict one already at the address.
        if at_address is not None and at_address != page.pk:
            raise ValueError(
                f"Page {page.title!r} was given pk {page.pk}, but the Title at "
                f"that address already has pk {at_address}"
            )
        if (
            at_address is None
            and connection.execute(select(Title.pk).where(Title.pk == page.pk)).scalar()
            is None
        ):
            _insert_title(connection, page, pk=page.pk)


def _insert_title(connection, page: Page, *, pk: int | None = None) -> int:
    values = {
        "site_pk": page.site_pk,
        "title": page.title,
        "expected_content_model": page.content_model or _WIKITEXT,
    }
    if pk is not None:
        values["pk"] = pk
    return connection.execute(insert(Title).values(**values)).inserted_primary_key[0]
