from datetime import datetime

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow

"""One revision of one page, mirroring MediaWiki's ``revision`` table.

Deliberately **sparse**: a row exists for each revision we have actually
fetched, and the absence of a row never means the revision does not exist. That
is the same known-absent/unknown distinction ``Page`` already carries for
placeholders, one level down -- and getting it wrong would let a base search
report a fork point that is only the oldest row we happen to hold. ``Page``
records how much of the history is known.

Two deliberate divergences from MediaWiki's schema:

- ``rev_actor``/``rev_comment_id`` normalisation is dropped. It exists to dedupe
  across billions of rows; we hold thousands, so contributor and comment are
  inline.
- ``rev_sha1``/``rev_len`` are dropped entirely. For a single-slot revision
  MediaWiki's ``rev_sha1`` *is* the main slot's ``content_sha1`` and ``rev_len``
  its ``content_size``, so carrying them here would be the same number under a
  second name -- and a second name is exactly what made this area hard to reason
  about. Upstream reached the same conclusion: T389026 ("Rethink rev_sha1
  field") is resolved as *"drop rev_sha1 and compute it on the fly from
  content_sha1"*. Read them through the slot; for a hypothetical multi-slot
  revision, combine the slots' hashes the way MediaWiki does rather than storing
  a third thing.
"""


class Revision(SQLModel, table=True):
    """A fetched revision. Content hangs off it via ``Slot``, one row per role."""

    __table_args__ = (
        UniqueConstraint("page_pk", "revid", name="uq_revision_page_revid"),
    )

    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk", index=True)

    # Site-local and not comparable across wikis -- the same caveat as
    # Page.pageid. Ancestry within one wiki, nothing more.
    revid: int = Field(index=True)
    parent_revid: int | None = None

    timestamp: datetime | None = None
    contributor: str | None = None
    comment: str | None = None
    minor: bool = False

    observed_at: datetime = Field(default_factory=utcnow)
    """When we fetched this revision -- distinct from ``timestamp``, which is
    when the wiki recorded it. Conflating the two is a known bug class here."""

    def __repr__(self) -> str:  # pragma: no cover - convenience only
        return f"Revision(pk={self.pk}, page_pk={self.page_pk}, revid={self.revid})"
