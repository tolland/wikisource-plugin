from sqlmodel import Field, SQLModel

"""The wiki has a page at this title.

**Row presence is existence.** There is no ``exists`` flag and no tri-state:
the question "does the wiki hold this page" is answered by whether this row is
there. A page deleted upstream drops its ``WikiPage`` and keeps its ``Title``,
its journal, its links and its metadata -- which the old single-table shape
could not express without nulling five columns and hoping nothing read them.

Every column here is non-null and meaningless for a title the wiki has
nothing at, which is the whole reason they are in a row that only exists when
it does.

**Revision properties are deliberately absent.** ``revid``, ``remote_timestamp``,
``contributor`` and ``comment`` used to sit beside ``pageid``; they are
properties of a *revision*, and MediaWiki's own ``page`` table holds only
``page_id`` and ``page_latest`` while the rest lives in ``revision``. Keeping
both ``revid`` and ``latest_revision_pk`` is the dual-writer denormalisation
that made ``_is_placeholder`` read through ``head_revision`` rather than trust
the column next to it. Read them off the head Revision.
"""


class WikiPage(SQLModel, table=True):
    """The upstream page for a Title. Exists iff the wiki does."""

    title_pk: int = Field(foreign_key="title.pk", primary_key=True)
    """PK and FK at once: one WikiPage per Title, or none."""

    pageid: int
    namespace_key: int
    """Site-local numeric namespace id. Informational -- roles are resolved
    per-site from siteinfo, since Page/Index ids differ between wikis."""

    content_model: str
    """MediaWiki's ``page_content_model``. A *page* fact, not a namespace one:
    a namespace can hold several models, and under MCR each slot carries its
    own (see ``Content.content_model``, which is authoritative per slot).

    A Title with no WikiPage has no stored model at all. Code that needs one
    for an unsaved page -- the editor, ``dispatch`` -- asks for the namespace
    default from siteinfo through an explicitly named lookup, so a prediction
    is never mistaken for a fetched fact."""

    latest_revision_pk: int
    """The head Revision row -- our analogue of ``page_latest``.

    Deliberately *not* a declared foreign key. Revision already points at
    Title, and declaring the reverse creates a cycle SQLAlchemy cannot order;
    under ``PRAGMA foreign_keys=ON`` it would also block deleting a head
    revision. MediaWiki's own DDL declares no foreign keys either."""

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return f"WikiPage(title_pk={self.title_pk}, pageid={self.pageid})"
