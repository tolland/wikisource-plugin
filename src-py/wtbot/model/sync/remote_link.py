from enum import Enum

from sqlalchemy import Index, text
from sqlmodel import Field, SQLModel

"""An assertion that two revisions, one per site, are the same content.

Correspondence is **asserted and recorded, never computed from hashes**. A
`proofread-page` body carries its own metadata in its text --
``<pagequality level="3" user="Hesperian" />`` -- where ``user`` names an
account on one wiki and ``level`` is that wiki's proofreading state. Proofreading
a page locally is precisely the act of changing both, so two identical
transcriptions routinely hash differently, and they diverge further exactly as
the work progresses. A hash match is strong evidence of sameness; a mismatch is
no evidence of difference. See docs/design/upstream-sync-discussion.md section 3.

Links are **append-only**. Nothing here is ever updated in place: when a human
re-anchors two diverged sides by making them identical again, that is a new row
with ``origin=reconciled``, not an edit to the old one. The rows for a page pair
are the ladder; the most recently inserted is the current anchor.

Page-level correspondence used to be *derived* from these rows. It is now
stored, as ``PageLink``, and every rung belongs to one -- see that module for
why derivation could not represent the pairs that most need attention (a
diverged pair, or one where a side is unfetched, has no linkable revision and
so derived into nothing).
"""


class LinkOrigin(str, Enum):
    """How the correspondence came to be asserted.

    Kept because the four cases carry different trust, and the promotion path
    treats them differently -- not as free-text provenance.
    """

    copy = "copy"
    """One side was created from the other. The strongest claim available: the
    correspondence is a fact about how the revision came to exist."""

    title_match = "title_match"
    """Matched by normalised title (namespace *role* plus page number), then
    confirmed. Proposals are never auto-confirmed, so a stored row of this
    origin has been through a human."""

    manual = "manual"
    """Asserted by hand, typically where titles differ between the sites."""

    reconciled = "reconciled"
    """Forward re-anchoring: two sides had diverged, a human made them
    content-identical, and this row is the new base. Remote history is
    append-only -- there is no rebase and no discoverable merge base -- so a
    broken anchor is re-established going forward rather than found in the
    past. See discussion section 2."""


class RevisionLink(SQLModel, table=True):
    """One asserted correspondence between a local and a remote revision.

    Deliberately narrow. An earlier sketch carried ``confidence``,
    ``asserted_at``, ``asserted_by`` and ``note``; all four are omitted until
    something reads them. ``confidence`` in particular has no home here --
    a proposal's score belongs to the proposal, and a link that is not
    confident should not be stored. Insertion order, which is what "the most
    recent link is the anchor" needs, is carried by the monotonic ``pk``.

    **The pair is unordered.** ``local`` and ``remote`` record the direction the
    assertion was made from -- which side ``origin=copy`` copied from, which
    site the operator was looking at -- but neither is privileged, and nothing
    stops a later caller naming them the other way round. "A corresponds to B"
    and "B corresponds to A" are the same fact, so storing both would give one
    page pair two ladders and two anchors that could disagree. That is the kind
    of error every layer above would inherit, so it is prevented here rather
    than checked for later.

    One revision may be linked once per *other site*: A may correspond to B on
    upstream1 and C on upstream2, but never to two different revisions on
    upstream1. That rule depends on Revision -> Page -> Site joins and therefore
    cannot be expressed by an index over this table; ``assert_link`` enforces it
    at the sole writing boundary.
    """

    __table_args__ = (
        # Unique on the *unordered* pair. A plain UniqueConstraint over
        # (local, remote) would happily admit the same link reversed; SQLite
        # indexes expressions, so min/max canonicalises the pair for the index
        # without the columns having to lie about which side is which.
        Index(
            "uq_remotelink_pair",
            text("min(local_revision_pk, remote_revision_pk)"),
            text("max(local_revision_pk, remote_revision_pk)"),
            unique=True,
        ),
    )

    pk: int | None = Field(default=None, primary_key=True)

    page_link_pk: int | None = Field(
        default=None, foreign_key="pagelink.pk", index=True
    )
    """The pairing this rung belongs to.

    Nullable only because rows written before ``PageLink`` existed have their
    pairing backfilled by migration; the store never writes None. ``local`` and
    ``remote`` below follow the parent's orientation, so a ladder reads one way
    round rather than reconciling two."""

    local_revision_pk: int = Field(foreign_key="revision.pk", index=True)
    remote_revision_pk: int = Field(foreign_key="revision.pk", index=True)

    origin: LinkOrigin

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return (
            f"RemoteLink(pk={self.pk}, local={self.local_revision_pk}, "
            f"remote={self.remote_revision_pk}, origin={self.origin.value})"
        )
