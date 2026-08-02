"""fold the pix2tex OCR backend kind into wikimedia

``pix2tex`` used to be its own OcrBackendKind, pointing straight at a
``lukasblecher/pix2tex:api`` container and doing its own download/crop with
Pillow before a multipart upload. py-ocrapi now fronts pix2tex behind the
same URL+crop+rotate contract as tesseract and Google Vision, so pix2tex is
just another ``engine`` value on a ``wikimedia`` row.

Existing rows are rewritten in place: kind ``pix2tex`` becomes ``wikimedia``
with default_engine ``pix2tex``. Their ``base_url`` is deliberately left
alone and cannot be fixed up here — it points at a bare pix2tex container,
which does not serve ``/api``, so the row has to be re-pointed at a
py-ocrapi instance by hand. Converting rather than deleting keeps that
visible (a run fails with a clear HTTP error) instead of silently dropping
a backend someone configured.

Revision ID: d5e30ab914c7
Revises: c9d21f6a4b5e
Create Date: 2026-08-01 00:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e30ab914c7"
down_revision: str | None = "d4a7b1e6c5f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ocrbackendconfig = sa.table(
    "ocrbackendconfig",
    sa.column("kind", sa.String()),
    sa.column("default_engine", sa.String()),
)


def upgrade() -> None:
    op.execute(
        ocrbackendconfig.update()
        .where(ocrbackendconfig.c.kind == "pix2tex")
        .values(kind="wikimedia", default_engine="pix2tex")
    )


def downgrade() -> None:
    op.execute(
        ocrbackendconfig.update()
        .where(
            sa.and_(
                ocrbackendconfig.c.kind == "wikimedia",
                ocrbackendconfig.c.default_engine == "pix2tex",
            )
        )
        .values(kind="pix2tex", default_engine=None)
    )
