import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

import wtbot.model  # noqa: F401 - registers every table on SQLModel.metadata
from wtbot.db import alembic_config, create_db_engine, init_db

"""The pre-release history starts from one squashed schema baseline.

There are no supported databases at an intermediate revision. Existing
development databases already have the final schema and retain the baseline's
revision ID, while a fresh database creates that schema directly.
"""

BASELINE = "8ac41e2d7f90"
THROTTLE = "e7f3b415fd0a"
HEAD = "f19c2d4a7b31"


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
        THROTTLE,
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


def test_old_multi_page_promotion_batch_is_split_by_page(
    baseline_engine: Engine,
) -> None:
    _run(baseline_engine, command.upgrade, THROTTLE)
    with baseline_engine.begin() as connection:
        connection.execute(text("""
                INSERT INTO site
                    (pk, family, code, articlepath, label, created_at)
                VALUES
                    (1, 'source', 'en', '/wiki/$1', 'source', CURRENT_TIMESTAMP),
                    (2, 'target', 'en', '/wiki/$1', 'target', CURRENT_TIMESTAMP)
                """))
        connection.execute(text("""
                INSERT INTO page
                    (pk, site_pk, title, namespace_role, dirty, fetch_status)
                VALUES
                    (1, 1, 'Page:Book/1', 'page', 0, 'done'),
                    (2, 1, 'Page:Book/2', 'page', 0, 'done')
                """))
        connection.execute(text("""
                INSERT INTO revision
                    (pk, page_pk, revid, minor, observed_at)
                VALUES
                    (1, 1, 101, 0, CURRENT_TIMESTAMP),
                    (2, 2, 102, 0, CURRENT_TIMESTAMP)
                """))
        connection.execute(text("""
                INSERT INTO promotionbatch
                    (pk, source_site_pk, target_site_pk, source_index_title,
                     target_index_title, status, created_at)
                VALUES
                    (1, 1, 2, 'Index:Book', 'Index:Book', 'draft', CURRENT_TIMESTAMP)
                """))
        connection.execute(text("""
                INSERT INTO promotion
                    (pk, batch_pk, source_page_pk, target_title, page_number,
                     intent, source_revision_pk, source_head_revid, body,
                     status, staged_at)
                VALUES
                    (1, 1, 1, 'Page:Book/1', 1, 'create', 1, 101,
                     'one', 'staged', CURRENT_TIMESTAMP),
                    (2, 1, 2, 'Page:Book/2', 2, 'create', 2, 102,
                     'two', 'staged', CURRENT_TIMESTAMP)
                """))

    _run(baseline_engine, command.upgrade, "head")

    with baseline_engine.connect() as connection:
        batches = connection.execute(
            text(
                "SELECT pk, source_page_pk, source_title, target_title, page_number "
                "FROM promotionbatch ORDER BY page_number"
            )
        ).all()
        promotions = connection.execute(
            text("SELECT batch_pk, source_revision_pk FROM promotion ORDER BY pk")
        ).all()
        promotion_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(promotion)"))
        }

    assert [row[1:] for row in batches] == [
        (1, "Page:Book/1", "Page:Book/1", 1),
        (2, "Page:Book/2", "Page:Book/2", 2),
    ]
    assert [row[0] for row in promotions] == [batches[0][0], batches[1][0]]
    assert "source_page_pk" not in promotion_columns


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
