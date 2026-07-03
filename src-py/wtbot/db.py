from collections.abc import Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

# Importing the models registers them on SQLModel.metadata so create_all works.
import wtbot.model  # noqa: F401

"""SQLite engine wiring and pragma discipline.

Every connection gets WAL, a busy timeout, and foreign keys. Transaction
handling is the driver's normal style: reads run in autocommit, and the
write lock is taken when a write statement actually executes.

An earlier iteration forced ``BEGIN IMMEDIATE`` on *every* transaction so
the write lock was held from the first SELECT of a request to its commit.
That proved unreliable — any second session (a concurrent request, a worker
loop, a test fixture) stalled on ``busy_timeout`` behind a lock the holder
mostly used for reading, and the workers/tests grew rollback and AUTOCOMMIT
workarounds to escape it. Under WAL, readers need no lock at all, so the
eager write lock bought nothing for the read-heavy VFS traffic.
"""

DEFAULT_SQLITE_URL = "sqlite:///database.db"


def create_db_engine(url: str = DEFAULT_SQLITE_URL, *, echo: bool = False) -> Engine:
    engine = create_engine(
        url,
        echo=echo,
        # FastAPI may hit a connection from a worker thread.
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    return engine


def init_db(engine: Engine) -> None:
    """Create any missing tables. (A real migration tool comes later; for now the
    models are the source of truth and this is create-if-absent.)"""
    SQLModel.metadata.create_all(engine)


def session_factory(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session
