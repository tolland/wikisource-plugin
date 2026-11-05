"""Add the change feed table.

Revision ID: d4b1f7a92c60
Revises: c92a713e4b06
"""

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision = "d4b1f7a92c60"
down_revision = "c92a713e4b06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "changeevent",
        sa.Column("pk", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "topic",
            sa.Enum("fetch", "drain", name="eventtopic"),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum(
                "queued",
                "done",
                "failed",
                "retried",
                "cancelled",
                "drain_started",
                "drain_finished",
                name="eventkind",
            ),
            nullable=False,
        ),
        sa.Column(
            "level",
            sa.Enum("info", "warning", "error", name="eventlevel"),
            nullable=False,
        ),
        sa.Column("site_pk", sa.Integer(), nullable=True),
        sa.Column("request_pk", sa.Integer(), nullable=True),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("message", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("failure_kind", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("retry_after", sa.Float(), nullable=True),
        sa.Column("detail", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.PrimaryKeyConstraint("pk", name=op.f("pk_changeevent")),
    )
    op.create_index(op.f("ix_changeevent_at"), "changeevent", ["at"])
    op.create_index(op.f("ix_changeevent_topic"), "changeevent", ["topic"])
    op.create_index(op.f("ix_changeevent_request_pk"), "changeevent", ["request_pk"])


def downgrade() -> None:
    op.drop_table("changeevent")
