"""drop wiki-coupled ocrbackendconfig

OCR backend configuration moved out of wtbot's schema into the standalone
``ocrapi`` package (src-py/ocrapi/model.py): the table is no longer keyed
by a foreign key into wtbot's ``site`` table, but by a plain ``scope``
string, so it carries no dependency on wtbot's schema at all. wtbot now
mounts ocrapi's app at /ocr and lets ``ocrapi.db.init_ocr_db`` (a plain
``create_all``, run on startup) create the new-shaped table against the
same shared database file — this migration's job is only to clear out the
old shape first so that create_all's "already exists" check doesn't see a
stale table with the wrong columns.

Revision ID: b81f4c0d9e23
Revises: a2c7e94f1b6d
Create Date: 2026-07-29 00:00:00.000000+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b81f4c0d9e23"
down_revision: str | None = "a2c7e94f1b6d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_ocrbackendconfig_site_pk", table_name="ocrbackendconfig")
    op.drop_table("ocrbackendconfig")


def downgrade() -> None:
    # Not reversible: the wiki-coupled shape and any rows in it are gone.
    # ocrapi.db.init_ocr_db recreates the new (scope-based) shape on next
    # startup regardless of alembic state.
    pass
