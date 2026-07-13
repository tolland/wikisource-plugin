from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine

# Importing the models registers them on SQLModel.metadata for Alembic.
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
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parents[1]


def create_db_engine(
    url: str = DEFAULT_SQLITE_URL, *, echo: bool | str = False
) -> Engine:
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


def alembic_config(url: str | None = None) -> Config:
    ini_path = PROJECT_ROOT / "alembic.ini"
    cfg = Config(str(ini_path)) if ini_path.exists() else Config()
    cfg.set_main_option("script_location", str(PACKAGE_ROOT / "migrations"))
    src_path = PROJECT_ROOT / "src-py"
    cfg.set_main_option(
        "prepend_sys_path", str(src_path if src_path.exists() else PACKAGE_ROOT.parent)
    )
    if url is not None:
        cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def upgrade_db(engine: Engine | None = None, revision: str = "head") -> None:
    cfg = alembic_config()
    if engine is None:
        command.upgrade(cfg, revision)
        return

    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)


def init_db(engine: Engine) -> None:
    """Bring the database schema up to the latest Alembic revision."""
    upgrade_db(engine)


def stamp_db(engine: Engine, revision: str = "head") -> None:
    cfg = alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.stamp(cfg, revision)


def session_factory(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session
