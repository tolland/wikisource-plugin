from datetime import datetime
from enum import Enum

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

"""A title of a page on a site: an address whose content we may not know yet.

Named after MediaWiki's own ``Title``, and split from ``Page`` for the same
reason MediaWiki splits ``Title`` from ``WikiPage``: a title is an address,
and whether the wiki holds anything at it is a separate question with a
separate answer. A paginated ``Page:`` nobody has transcribed has a title, a
scan, a proposed body and a page number, and a user can open, edit and save
it -- none of which needs the wiki to have a page there.

**Every Page is a Title; not every Title is a Page yet.** ``page.pk`` is a
foreign key to ``title.pk`` -- a shared primary key, so any value that
identifies a page also identifies its title. That is what lets the split
happen progressively: an existing foreign key to ``page.pk`` is already a
valid ``title.pk``, and repointing one is a change of constraint, not of data.

The transition is recorded in docs/design/pages-and-existence.md. What
belongs to the address lives here -- the expected content model, namespace,
fetch status and dirty flag -- and everything keyed by address (journal,
commits, proofread metadata, annotations, pairings) references this table.
A Page reaches its Title as ``Page.address``.
"""


class FetchState(str, Enum):
    unfetched = "unfetched"
    pending = "pending"
    fetching = "fetching"
    done = "done"
    error = "error"


class Title(SQLModel, table=True):
    """One (site, title) address, fetched or not, existing or not."""

    __table_args__ = (UniqueConstraint("site_pk", "title"),)

    pk: int | None = Field(default=None, primary_key=True)
    site_pk: int = Field(foreign_key="site.pk", index=True)

    title: str
    """Full title including the namespace prefix, e.g. ``Page:Foo.djvu/171``.

    ``Page.title`` still exists during the transition and must agree with this.
    It is written once, when both rows are created; nothing renames a page yet.
    """

    expected_content_model: str
    """The content model we *expect* a save at this title to have. A guess.

    Needed before anything is fetched, because the editor has to open a title
    as something, and metadata such as ``ProofreadPageMeta`` hangs off what a
    title is expected to be. The guess comes from context: an Index fan-out
    knows its children are ``proofread-page``; a file opened in the client has
    an extension; otherwise MediaWiki's own fallback, ``wikitext``.

    A namespace alone does not decide it -- ``Index:Foo.pdf/styles.css`` is in
    the Index namespace and is ``sanitized-css`` -- which is why this is never
    derived from namespace identity.

    ``Page.content_model`` is what the wiki said, once it has said anything.
    The fetch compares the two, warns when the guess was wrong, and corrects
    it (see ``wtbot.title_store.record_fetched_content_model``).
    """

    namespace_key: int | None = None
    """Site-local namespace id, resolving against ``Namespace`` for this site.

    What the wiki said when the title was fetched; None until then. It could be
    derived from the title's prefix and the site's namespace map, and may be
    once titles are created from the client."""

    fetch_status: FetchState = Field(
        default=FetchState.unfetched,
        sa_column_kwargs={"server_default": FetchState.unfetched.value},
    )
    """Whether we have asked the wiki about this address.

    ``done`` with no ``Page`` behind it is the answer "absent" -- as against
    ``unfetched``, where the answer is unknown. That distinction is the
    title's to hold because the absent case has no page to hold it. (Only
    ``unfetched`` and ``done`` are written; the queue's own progress is
    ``FetchRequest.status``.)"""

    dirty: bool = Field(
        default=False, index=True, sa_column_kwargs={"server_default": "0"}
    )
    """Local edits not yet committed: a save appends to ``EditJournal`` and
    sets this; a commit (or a fetch) clears it. An address property because a
    title the wiki does not hold yet can be edited and saved."""

    local_modified_at: datetime | None = None
    """When a local save last touched this address. Deliberately distinct from
    the page's ``remote_timestamp`` -- conflating them is a known bug class."""

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return f"Title(pk={self.pk}, title={self.title!r})"
