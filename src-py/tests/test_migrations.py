import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

import wtbot.model  # noqa: F401 - registers every table on SQLModel.metadata
from wtbot.db import alembic_config, create_db_engine, init_db

"""The pre-release migration history is intentionally one final-schema baseline.

There are no supported databases at an intermediate revision. Existing
development databases already have the final schema and retain the baseline's
revision ID, while a fresh database creates that schema directly.
"""

BASELINE = "8ac41e2d7f90"
HEAD = "e7f3b415fd0a"


@pytest.fixture
def baseline_engine(tmp_path) -> Engine:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'baseline.db'}")
    try:
        yield engine
    finally:
        engine.dispose()


def _run(engine: Engine, operation, revision: str) -> None:
    config = alembic_config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        operation(config, revision)


def test_history_starts_at_the_squashed_baseline() -> None:
    script = ScriptDirectory.from_config(alembic_config())

    assert script.get_heads() == [HEAD]
    assert [revision.revision for revision in script.walk_revisions()] == [
        HEAD,
        BASELINE,
    ]


def test_baseline_creates_the_current_model_schema(baseline_engine: Engine) -> None:
    _run(baseline_engine, command.upgrade, "head")

    with baseline_engine.connect() as connection:
        config = alembic_config()
        config.attributes["connection"] = connection
        command.check(config)

        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
        }
        indexes = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'index'")
            )
        }
        current = connection.execute(text("SELECT version_num FROM alembic_version"))

        assert set(SQLModel.metadata.tables) <= tables
        assert current.scalar_one() == HEAD
        # Alembic cannot reflect SQLite expression indexes, so command.check()
        # deliberately skips them and they need an explicit assertion.
        assert {"uq_pagelink_pair", "uq_revisionlink_pair"} <= indexes


def test_an_existing_final_database_at_the_retained_revision_is_untouched(
    baseline_engine: Engine,
) -> None:
    _run(baseline_engine, command.upgrade, BASELINE)
    with Session(baseline_engine) as session:
        session.exec(
            text(
                "INSERT INTO site (family, code, articlepath, created_at)"
                " VALUES ('wikisource', 'en', '/wiki/$1', CURRENT_TIMESTAMP)"
            )
        )
        session.commit()

    init_db(baseline_engine)

    with Session(baseline_engine) as session:
        site = session.exec(text("SELECT family, code, read_throttle FROM site")).one()
        assert site == ("wikisource", "en", None)


def test_baseline_can_be_downgraded_to_an_empty_database(
    baseline_engine: Engine,
) -> None:
    _run(baseline_engine, command.upgrade, "head")
    _run(baseline_engine, command.downgrade, "base")

    with baseline_engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
        }
    assert tables == {"alembic_version"}
