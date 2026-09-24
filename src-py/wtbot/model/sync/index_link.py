from datetime import datetime

from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow

"""The work-level correspondence: two ``Index:`` pages that are the same work.

For Wikisource the unit of comparison is the Index, not the page. An Index is
to a work what a repository is to its files: pages are compared, promoted and
reconciled *within* one, and "is this work tracked against upstream?" is the
question a reviewer asks first and the one the viewer opens on.

**Why this is a side table on ``PageLink`` rather than a table of its own.**
An ``Index:`` page is a ``Page`` row like any other, so the claim "these two
Index pages are the same page" is already exactly a ``PageLink``. Giving works
their own pairing table would mean two tables that can each assert page
correspondence, two unordered-pair constraints that cannot see each other, and
a live question at every call site about which one to trust. It would also
throw away something real: an Index has *content* -- the pagelist, the volume
metadata, the transclusion structure -- which diverges across sites exactly as
a page's does, and a pairing carries a ladder of revision links for free.

So the pairing stays one thing and this records what that pairing *is*: the
same relationship ``IndexMeta`` has to ``Page``, which is the established shape
here. ``Page`` stays one table and content-specific attributes hang off it; page
pairings stay one table and the work-level ones hang off this.

**A work's page pairs are derived, not claimed.** A pair belongs to a work when
one of its pages is a child of either of the work's indexes -- read off that
page's ``ProofreadPageMeta.index_title_pk`` -- and the other page is on the other
index's site. Keyed through the index's *pk*, this does not have the problem
title matching had (the two sides' index titles may differ), and it cannot go
stale the way a stored pointer could. Pairs asserted before the work was
tracked belong to it the moment it is; nothing has to adopt them.
"""


class IndexLink(SQLModel, table=True):
    """One tracked work: a page pairing between two ``Index:`` pages.

    Deliberately thin. Everything about *which* two pages, in which
    orientation, and how the correspondence was arrived at already lives on the
    ``PageLink`` this extends; duplicating any of it here would create a second
    answer to a question that already has one. What is left is what only a work
    has: when tracking started, and (later) where its sync got to.
    """

    pk: int = Field(primary_key=True, foreign_key="pagelink.pk")
    """Shared with the ``PageLink`` pairing the two ``Index:`` pages: every work
    *is* a pairing, and at most one work per pairing follows from the key
    itself -- no separate reference, no separate unique index."""

    created_at: datetime = Field(default_factory=utcnow)
    """When the work was put under tracking -- distinct from the pairing's own
    ``created_at``, which may be older: a work's pages can be paired long
    before anyone declares the work itself tracked."""

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return f"IndexLink(pk={self.pk})"
