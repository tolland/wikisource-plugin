"""Use content models and namespace identity instead of stored classifications."""

import sqlalchemy as sa
from alembic import op

revision = "c38d2e7f901a"
down_revision = "b72e8c913a04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Old placeholders may have no namespace_key. Recover it only from this
    # site's actual namespace map, or the fixed core File namespace identity.
    # Do not translate extension names to hard-coded numeric namespace IDs.
    op.execute(sa.text("""
        UPDATE page SET namespace_key = (
            SELECT n.key FROM namespace n
            WHERE n.site_pk = page.site_pk
              AND (n.canonical_name = substr(page.title, 1, instr(page.title, ':') - 1)
                   OR n.local_name = substr(page.title, 1, instr(page.title, ':') - 1))
              AND instr(page.title, ':') > 0
            LIMIT 1
        ) WHERE namespace_key IS NULL
        """))
    op.execute(sa.text("""
        UPDATE page SET namespace_key = 6
        WHERE namespace_key IS NULL AND namespace_role = 'file'
        """))
    # Existing placeholders already carry their content_model. Leave unknown
    # models unknown: a namespace alone cannot tell us whether content is a
    # proofread page, CSS, JSON, or something else.
    # Native DROP COLUMN avoids rebuilding parent tables with FK dependents.
    op.drop_column("page", "namespace_role")
    op.drop_column("namespace", "role")


def downgrade() -> None:
    op.add_column(
        "namespace",
        sa.Column("role", sa.String(8), nullable=False, server_default="other"),
    )
    op.add_column(
        "page",
        sa.Column(
            "namespace_role", sa.String(8), nullable=False, server_default="other"
        ),
    )
    # Reconstruct the previous derived classification from namespace identity.
    op.execute(sa.text("""
        UPDATE namespace SET role = CASE
            WHEN canonical_name = '' THEN 'main'
            WHEN canonical_name IN
                ('Page', 'Index', 'File', 'Template', 'Module', 'Category', 'Author', 'Book')
            THEN lower(canonical_name)
            ELSE 'other' END
        """))
    op.execute(sa.text("""
        UPDATE page SET namespace_role = COALESCE(
            (SELECT n.role FROM namespace n
             WHERE n.site_pk = page.site_pk AND n.key = page.namespace_key),
            CASE WHEN namespace_key = 6 THEN 'file'
                 WHEN namespace_key = 0 THEN 'main'
                 WHEN content_model = 'proofread-page' THEN 'page'
                 WHEN content_model = 'proofread-index' THEN 'index'
                 ELSE 'other' END)
        """))
