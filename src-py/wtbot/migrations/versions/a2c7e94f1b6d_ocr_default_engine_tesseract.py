"""default OCR engine to tesseract

Backfills existing ocrbackendconfig rows with a NULL default_engine to
"tesseract" — Wikimedia OCR's free/local engine — so a config that never
specified an engine doesn't silently fall through to a paid one (e.g.
Google). New rows already default here at the model/API layer; this only
catches rows created before that default existed.

Revision ID: a2c7e94f1b6d
Revises: f3b82d17c9a4
Create Date: 2026-07-28 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2c7e94f1b6d"
down_revision: str | None = "f3b82d17c9a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ocrbackendconfig = sa.table(
    "ocrbackendconfig", sa.column("default_engine", sa.String())
)


def upgrade() -> None:
    op.execute(
        ocrbackendconfig.update()
        .where(ocrbackendconfig.c.default_engine.is_(None))
        .values(default_engine="tesseract")
    )


def downgrade() -> None:
    # Not reversible: we can't tell backfilled rows from ones that were
    # genuinely "tesseract" already.
    pass
