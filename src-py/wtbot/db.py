"""SQLite engine wiring and the IPC pragma discipline.

Both processes that touch ``database.db`` (this backend and the IntelliJ plugin)
must use WAL, a busy timeout, and ``BEGIN IMMEDIATE`` for writes. We enforce all
three here for the Python side via SQLAlchemy connection events.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

# Importing the models registers them on SQLModel.metadata so create_all works.
import wtbot.sqlmodel  # noqa: F401

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
        # Disable pysqlite's implicit transaction handling so we control BEGIN
        # ourselves (and can make it IMMEDIATE below).
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn):  # noqa: ANN001
        # IMMEDIATE takes the write lock up front, matching the Kotlin side and
        # avoiding the deferred-to-write upgrade deadlock under concurrency.
        conn.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


def init_db(engine: Engine) -> None:
    """Create any missing tables. (A real migration tool comes later; for now the
    models are the source of truth and this is create-if-absent.)"""
    SQLModel.metadata.create_all(engine)


def session_factory(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session
