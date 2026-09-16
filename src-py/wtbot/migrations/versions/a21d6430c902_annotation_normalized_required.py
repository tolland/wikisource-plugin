"""Require backfilled normalized geometry and remove legacy pixel columns."""

import sqlalchemy as sa
from alembic import op

revision = "a21d6430c902"
down_revision = "a21d6430c901"
branch_labels = None
depends_on = None


def upgrade() -> None:
    invalid = op.get_bind().execute(sa.text("""
        SELECT count(*) FROM scanannotation
        WHERE normalized_x IS NULL OR normalized_y IS NULL
           OR normalized_width IS NULL OR normalized_height IS NULL
           OR normalized_x < 0 OR normalized_y < 0
           OR normalized_width <= 0 OR normalized_height <= 0
           OR normalized_x + normalized_width > 1.000000001
           OR normalized_y + normalized_height > 1.000000001
    """)).scalar_one()
    if invalid:
        raise RuntimeError(
            f"{invalid} annotations need backfilling. Upgrade to a21d6430c901, "
            "run src-py/scripts/normalize_scan_annotations.py, then upgrade head."
        )
    with op.batch_alter_table("scanannotation") as batch:
        for name in ("x", "y", "width", "height"):
            batch.alter_column(
                f"normalized_{name}", existing_type=sa.Float(), nullable=False
            )
            batch.drop_column(name)


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(sa.text("SELECT count(*) FROM scanannotation"))
        .scalar_one()
    ):
        raise RuntimeError(
            "Pixel coordinates cannot be reconstructed without the original image dimensions; restore the database backup."
        )
    with op.batch_alter_table("scanannotation") as batch:
        for name in ("x", "y", "width", "height"):
            batch.add_column(sa.Column(name, sa.Float(), nullable=False))
            batch.alter_column(
                f"normalized_{name}", existing_type=sa.Float(), nullable=True
            )
