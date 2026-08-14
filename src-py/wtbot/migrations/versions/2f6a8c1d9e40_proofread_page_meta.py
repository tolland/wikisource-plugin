"""create and backfill keyed ProofreadPageMeta

Revision ID: 2f6a8c1d9e40
Revises: d8f4a2c19e70
Create Date: 2026-08-14 12:00:00.000000+00:00

This intentionally leaves ``pagemeta`` in place. The following revision drops
it, making the data-copy boundary independently inspectable.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "2f6a8c1d9e40"
down_revision: str | None = "d8f4a2c19e70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _index_title(child_title: str, stored_title: str | None) -> str:
    if stored_title:
        return stored_title
    after_namespace = child_title.partition(":")[2]
    basename, separator, page_number = after_namespace.rpartition("/")
    if not separator or not basename or not page_number.isdigit():
        raise RuntimeError(
            f"cannot resolve owning Index for proofread page {child_title!r}"
        )
    return f"Index:{basename}"


def upgrade() -> None:
    op.create_table(
        "proofreadpagemeta",
        sa.Column("page_pk", sa.Integer(), nullable=False),
        sa.Column("index_page_pk", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("quality_level", sa.Integer(), nullable=True),
        sa.Column(
            "source_image_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column("default_body", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("thumb_url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("thumb_width", sa.Integer(), nullable=True),
        sa.Column("thumb_height", sa.Integer(), nullable=True),
        sa.Column("raster_path", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("thumb_path", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.ForeignKeyConstraint(["page_pk"], ["page.pk"]),
        sa.ForeignKeyConstraint(["index_page_pk"], ["page.pk"]),
        sa.PrimaryKeyConstraint("page_pk"),
    )
    op.create_index(
        op.f("ix_proofreadpagemeta_index_page_pk"),
        "proofreadpagemeta",
        ["index_page_pk"],
        unique=False,
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT p.pk AS page_pk, p.site_pk, p.title,"
            " m.index_title, m.page_number, m.quality_level,"
            " m.source_image_url, m.default_body, m.thumb_url,"
            " m.thumb_width, m.thumb_height, m.raster_path, m.thumb_path"
            " FROM pagemeta m JOIN page p ON p.pk = m.page_pk"
            " WHERE p.namespace_role = 'page'"
        )
    ).mappings()

    migrated = 0
    for row in rows:
        title = _index_title(row["title"], row["index_title"])
        index_identity = (
            connection.execute(
                sa.text(
                    "SELECT pk, namespace_role FROM page"
                    " WHERE site_pk = :site_pk"
                    " AND replace(title, '_', ' ') = replace(:title, '_', ' ')"
                    " ORDER BY pk LIMIT 1"
                ),
                {"site_pk": row["site_pk"], "title": title},
            )
            .mappings()
            .one_or_none()
        )
        if index_identity is not None and index_identity["namespace_role"] != "index":
            raise RuntimeError(
                f"owning Index title {title!r} resolves to non-Index page "
                f"{index_identity['pk']}"
            )
        index_pk = index_identity["pk"] if index_identity is not None else None
        if index_pk is None:
            result = connection.execute(
                sa.text(
                    "INSERT INTO page"
                    " (site_pk, title, namespace_role, content_model, dirty, fetch_status)"
                    " VALUES (:site_pk, :title, 'index', 'proofread-index', 0, 'unfetched')"
                ),
                {"site_pk": row["site_pk"], "title": title},
            )
            index_pk = result.lastrowid
            if index_pk is None:
                raise RuntimeError(f"failed to create Index identity for {title!r}")

        connection.execute(
            sa.text(
                "INSERT INTO proofreadpagemeta"
                " (page_pk, index_page_pk, page_number, quality_level,"
                " source_image_url, default_body, thumb_url, thumb_width,"
                " thumb_height, raster_path, thumb_path)"
                " VALUES (:page_pk, :index_page_pk, :page_number, :quality_level,"
                " :source_image_url, :default_body, :thumb_url, :thumb_width,"
                " :thumb_height, :raster_path, :thumb_path)"
            ),
            {**row, "index_page_pk": index_pk},
        )
        migrated += 1

    source_count = connection.execute(
        sa.text(
            "SELECT count(*) FROM pagemeta m"
            " JOIN page p ON p.pk = m.page_pk WHERE p.namespace_role = 'page'"
        )
    ).scalar_one()
    target_count = connection.execute(
        sa.text("SELECT count(*) FROM proofreadpagemeta")
    ).scalar_one()
    if source_count != migrated or target_count != source_count:
        raise RuntimeError(
            "ProofreadPageMeta backfill count mismatch: "
            f"source={source_count}, migrated={migrated}, target={target_count}"
        )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_proofreadpagemeta_index_page_pk"),
        table_name="proofreadpagemeta",
    )
    op.drop_table("proofreadpagemeta")
