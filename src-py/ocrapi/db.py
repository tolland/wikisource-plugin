from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import SQLModel, create_engine

from ocrapi.model import OcrBackendConfig

"""Standalone SQLite engine for ocrapi's own table.

No Alembic here: the package owns exactly one table, so a plain
``create_all`` (idempotent — a no-op once the table exists) is enough and
keeps a from-scratch checkout runnable with zero migration setup. A host
that embeds this app with its own Alembic-managed database (wtbot does)
just needs that database to include this table's shape; wtbot's own
migration history is what keeps that in sync there, and ``init_ocr_db``
stays a safe no-op against an already-correct table either way.
"""

DEFAULT_SQLITE_URL = "sqlite:///ocr.db"


def create_ocr_engine(
    url: str = DEFAULT_SQLITE_URL, *, echo: bool | str = False
) -> Engine:
    engine = create_engine(
        url,
        echo=echo,
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


def init_ocr_db(engine: Engine) -> None:
    """Creates the OCR backend-config table if it doesn't already exist."""
    SQLModel.metadata.create_all(engine, tables=[OcrBackendConfig.__table__])
