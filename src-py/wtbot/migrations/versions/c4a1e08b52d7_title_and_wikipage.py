"""Split Page into Title (the address) and WikiPage (exists iff the wiki does).

**This migration rebuilds the schema and does not carry data across.** That is
a deliberate choice for this change, not an oversight: `page` loses five
columns, gains a satellite table, and is renamed, and every one of the
seventeen foreign keys that pointed at `page.pk` now points at `title.pk`.
Under SQLite each of those repoints is a table rebuild, so a data-preserving
version would be twelve rebuilds carrying rows whose shape we are changing
underneath them -- far more risk than re-fetching a cache that exists to be
re-fetchable.

**Dump the annotation tables first.** They are the one part of this database a
rebuild cannot re-fetch from a wiki (see docs/reference/annotation-transfer.md)
-- `uv run wtbot annotations dump` before, `annotations load` after.

Everything else here is cache: pages, revisions, contents, file blobs and the
fetch queue all come back from a drain. Links, promotions and the edit journal
do not, so export them too if a live database matters.
"""

import sqlalchemy as sa
from alembic import op
from sqlmodel import SQLModel

import wtbot.model  # noqa: F401 - registers every table on SQLModel.metadata

revision = "c4a1e08b52d7"
down_revision = "b72e8c913a04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Drop by reflection, not from SQLModel.metadata: `page` is gone from the
    # model, so a metadata-driven drop would leave the very table this
    # migration exists to remove sitting in the database.
    existing = sa.MetaData()
    existing.reflect(bind=bind)
    for table in reversed(existing.sorted_tables):
        if table.name == "alembic_version":
            continue
        table.drop(bind=bind, checkfirst=True)

    SQLModel.metadata.create_all(bind)


def downgrade() -> None:
    # Not reversible: the old shape held `pageid`/`revid`/`remote_timestamp`/
    # `contributor`/`comment` on `page`, and nothing in the new shape records
    # which of those a given row once had. Recreate from a dump instead.
    raise NotImplementedError(
        "the Title/WikiPage split is not reversible; restore from a backup"
    )
