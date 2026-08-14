from datetime import datetime

from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel

from wtbot.model.sync.revision_link import LinkOrigin
from wtbot.timeutil import utcnow

"""An assertion that two pages, one per site, are the same page.

Correspondence used to be *derived* from the revision links -- walk
``link -> revision -> page`` and see what came back. That was wrong in three
ways, and each of them shows up as soon as a person looks at a work:

- **A pair with nothing linkable is unrepresentable.** Two diverged pages are
  still the same page; so are two pages where one side has not been fetched.
  Derivation can only report a pair once some revision pair has been asserted,
  so exactly the pages that need attention are the ones that disappear.
- **Titles are not stable.** A page moved on either wiki breaks any pairing
  recomputed from titles. A pk-keyed pair survives a rename, because it never
  mentioned the title.
- **There was nothing to enumerate.** "Show me this work's page pairs and their
  state" is the first thing a reviewer wants and the derivation could not
  answer it without re-deriving the whole index.

So the pairing is stored, and the revision links hang off it.

**PageLink is mutable; RemoteLink is not.** They are different kinds of claim.
"These two pages are the same page" is a statement about the present, and a
wrong one is corrected by deleting it -- which takes its revision links with
it, since they were only ever assertions *within* that pairing. "These two
revisions hold the same content" is a statement about two immutable objects: it
cannot stop being true, so it is superseded (a newer rung) rather than edited.
"""


class PageLink(SQLModel, table=True):
    """One page pair. ``local``/``remote`` fix the orientation its revision
    links are written in, so a ladder never has to reconcile two directions."""

    __table_args__ = (
        # Unique on the *unordered* pair, the same way RemoteLink is: a pairing
        # asserted the other way round is the same pairing, and two rows for it
        # would give one work two sets of ladders.
        Index(
            "uq_pagelink_pair",
            text("min(local_page_pk, remote_page_pk)"),
            text("max(local_page_pk, remote_page_pk)"),
            unique=True,
        ),
    )

    pk: int | None = Field(default=None, primary_key=True)

    local_page_pk: int = Field(foreign_key="page.pk", index=True)
    remote_page_pk: int = Field(foreign_key="page.pk", index=True)

    index_link_pk: int | None = Field(
        default=None, foreign_key="indexlink.pk", index=True
    )
    """The tracked work this pair belongs to, when it belongs to one.

    A materialised shortcut for the drill-down the viewer opens on: work ->
    its page pairs, as a join rather than a walk back through
    ``ProofreadPageMeta.index_page_pk``. Membership is still derived from the index when
    the work is linked; this records the answer.

    Null is ordinary, not missing data. A pairing outside any tracked work --
    mainspace, ``Portal:``, a page paired by hand before its work was -- has no
    work to point at, and the Index pairing that *carries* the ``IndexLink``
    does not point at itself."""

    origin: LinkOrigin = LinkOrigin.title_match
    """How the pairing was arrived at. Weaker evidence than a revision link's
    origin by nature -- pairing two pages by page number says nothing about
    whether their contents ever agreed."""

    created_at: datetime = Field(default_factory=utcnow)

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return (
            f"PageLink(pk={self.pk}, local={self.local_page_pk}, "
            f"remote={self.remote_page_pk})"
        )
