"""content.comparable_sha1: the model-aware digest, precomputed

Cross-site sameness could not be hashed. A ``proofread-page`` body embeds
``<pagequality level="3" user="X" />`` in its own text, so the same
transcription hashes differently on the two wikis and ``content_sha1`` --
which covers the bytes the API served -- says nothing useful across sites.
Sameness was therefore decided by parsing both bodies and comparing them
model-aware, on every comparison, and the anchor search does that against every
stored revision of a page.

This column holds the result of the normalisation the comparison performs:
site-local metadata blanked, significant metadata (the proofreading level)
folded in, then hashed. Two rows share it exactly when the comparison would
call them the same content, so the search compares two strings and parses only
the revision it settled on.

Backfilled from ``content.text``, because the value is a pure function of the
text and its model -- there is nothing to fetch and nothing that can be lost.
Left nullable so a row this migration could not derive (or one written by an
older wtbot against a newer schema) reads as "not computed" rather than as a
difference; the store fills those in as it passes them.

Revision ID: f1a6d94c30be
Revises: e5c93a17b820
Create Date: 2026-08-09 16:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a6d94c30be"
down_revision: str | None = "e5c93a17b820"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Chunked so a large content table is not read into memory in one go. The
#: backfill is a rewrite of every row either way; the chunking bounds the peak,
#: not the work.
CHUNK = 500


def upgrade() -> None:
    # Plain add_column, not batch mode: SQLite's batch rebuild would DROP
    # `content`, which `slot` references under PRAGMA foreign_keys=ON. See
    # e2f9c3a71b48 for the same trap in the other direction.
    op.add_column("content", sa.Column("comparable_sha1", sa.String(), nullable=True))
    op.create_index(
        op.f("ix_content_comparable_sha1"), "content", ["comparable_sha1"], unique=False
    )
    _backfill()


def _backfill() -> None:
    """Compute the digest for existing rows.

    Imports the application's own normalisation rather than re-implementing it
    here. The usual reason migrations avoid that -- application code moves on
    and leaves the migration computing something else -- is survivable for a
    derived cache: if the canonical form ever changes, the correction is a
    later migration recomputing the column, exactly as it would be for a
    frozen copy that had gone stale.
    """
    from wtbot.content_model import comparable_sha1

    connection = op.get_bind()
    rows = connection.execute(
        sa.text("SELECT pk, text, content_model FROM content")
    ).fetchall()

    updates = [
        {"pk": pk, "digest": comparable_sha1(text or "", content_model)}
        for pk, text, content_model in rows
    ]
    statement = sa.text("UPDATE content SET comparable_sha1 = :digest WHERE pk = :pk")
    for start in range(0, len(updates), CHUNK):
        connection.execute(statement, updates[start : start + CHUNK])


def downgrade() -> None:
    op.drop_index(op.f("ix_content_comparable_sha1"), table_name="content")
    op.drop_column("content", "comparable_sha1")
