from sqlmodel import Field, SQLModel

"""Revision-to-content mapping per role, mirroring MediaWiki's ``slots`` table.

Kept rather than collapsed into ``Revision`` because multi-slot content is not
hypothetical here: Commons ``File:`` pages carry both a ``main`` (wikitext) slot
and a ``mediainfo`` (wikibase-mediainfo) slot, and the fetch path already
follows ``site.image_repository()`` to Commons for scans. Collapsing would mean
silently dropping the structured metadata of every scan we touch.

``Page:`` and ``Index:`` are single-slot ``main`` today, so in practice most
revisions have exactly one row.
"""

MAIN_SLOT = "main"


class Slot(SQLModel, table=True):
    """One (revision, role) -> content mapping.

    Composite primary key on (revision_pk, role), as MediaWiki keys
    ``(slot_revision_id, slot_role_id)``. Roles are stored by name rather than
    through a ``slot_roles`` lookup table -- the indirection saves bytes at
    Wikimedia scale and costs a join at ours.
    """

    revision_pk: int = Field(foreign_key="revision.pk", primary_key=True)
    role: str = Field(default=MAIN_SLOT, primary_key=True)

    content_pk: int = Field(foreign_key="content.pk", index=True)

    origin_revid: int | None = None
    """MediaWiki's ``slot_origin``: the revision in which this slot's content
    was introduced. Equal to the revision's own id when this revision changed
    the slot, older when the slot was inherited unchanged -- which makes
    "did this edit touch this slot?" answerable without comparing content."""
