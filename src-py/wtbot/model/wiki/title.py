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

The transition is recorded in docs/design/pages-and-existence.md. This first
step introduces the table and the invariant; nothing reads from it yet except
the fetch-time content-model check.
"""


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

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return f"Title(pk={self.pk}, title={self.title!r})"
