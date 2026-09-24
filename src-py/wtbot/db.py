import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, event
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


def database_url() -> str:
    """Where the database lives, when the caller has not said.

    ``WTBOT_DATABASE_URL`` was already read by ``migrations/env.py`` but not by
    the application, so a deployment that pointed migrations at one file left
    the app on the relative default -- two databases, one of them unmigrated.
    Containerising made that immediate: the volume is not the working
    directory.
    """
    return os.environ.get("WTBOT_DATABASE_URL") or DEFAULT_SQLITE_URL


def create_db_engine(url: str | None = None, *, echo: bool | str = False) -> Engine:
    url = url or database_url()
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


class MigrationIntegrityError(RuntimeError):
    """A migration left rows whose foreign keys point at nothing."""


@contextmanager
def migration_connection(engine: Engine) -> Iterator[Connection]:
    """A connection fit for changing the schema, not just the data.

    SQLite changes a table's structure by rebuilding it: copy into a new table,
    drop the old one, rename. With ``foreign_keys=ON`` the drop fails whenever
    another table points at the old one, which in this schema is most of them
    -- the reason earlier migrations reached for native ``DROP COLUMN`` rather
    than rebuild. This follows SQLite's own procedure for that case
    (https://sqlite.org/lang_altertable.html#otheralter):

    1. foreign keys off, *before* the transaction, since the pragma is ignored
       inside one;
    2. every migration in one real transaction;
    3. ``PRAGMA foreign_key_check`` over the finished state, and roll the lot
       back if anything points at nothing;
    4. foreign keys back on.

    Checking the finished state is stricter than per-statement enforcement,
    not looser: it asks the same question of every row, after everything has
    moved.

    Step 2 needs the driver's transaction handling out of the way. pysqlite
    issues ``BEGIN`` only before INSERT/UPDATE/DELETE, so DDL ran outside any
    transaction and a failed migration rolled back only its data -- which is
    what alembic's "Will assume non-transactional DDL" was saying. Here the
    driver is set to autocommit and the transaction is ours.
    """
    with engine.connect() as connection:
        raw = connection.connection.dbapi_connection
        previous_isolation = raw.isolation_level
        raw.isolation_level = None
        try:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.exec_driver_sql("BEGIN")
            try:
                yield connection
                violations = connection.exec_driver_sql(
                    "PRAGMA foreign_key_check"
                ).all()
                if violations:
                    raise MigrationIntegrityError(
                        f"{len(violations)} row(s) reference nothing after "
                        f"migrating; rolled back. First: {tuple(violations[0])}"
                    )
                connection.exec_driver_sql("COMMIT")
            except BaseException:
                connection.exec_driver_sql("ROLLBACK")
                raise
        finally:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            raw.isolation_level = previous_isolation


def upgrade_db(engine: Engine | None = None, revision: str = "head") -> None:
    cfg = alembic_config()
    if engine is None:
        # The standalone path: env.py opens its own connection and applies the
        # same discipline there.
        command.upgrade(cfg, revision)
        return

    with migration_connection(engine) as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)


def init_db(engine: Engine) -> None:
    """Bring the database schema up to the latest Alembic revision."""
    upgrade_db(engine)


def stamp_db(engine: Engine, revision: str = "head") -> None:
    cfg = alembic_config()
    with migration_connection(engine) as connection:
        cfg.attributes["connection"] = connection
        command.stamp(cfg, revision)


def session_factory(engine: Engine) -> Iterator[Session]:
    with Session(engine) as session:
        yield session
