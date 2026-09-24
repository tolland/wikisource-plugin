import warnings

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel

import wtbot.model  # noqa: F401 - registers every table on SQLModel.metadata
from wtbot.db import (
    MigrationIntegrityError,
    alembic_config,
    create_db_engine,
    init_db,
    migration_connection,
)

"""The pre-release history starts from one squashed schema baseline.

There are no supported databases at an intermediate revision. Existing
development databases already have the final schema and retain the baseline's
revision ID, while a fresh database creates that schema directly.
"""

BASELINE = "8ac41e2d7f90"
THROTTLE = "e7f3b415fd0a"
HEAD = "c38d2e7f901a"


@pytest.fixture
def baseline_engine(tmp_path) -> Engine:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'baseline.db'}")
    try:
        yield engine
    finally:
        engine.dispose()


def _run(engine: Engine, operation, revision: str) -> None:
    config = alembic_config()
    with migration_connection(engine) as connection:
        config.attributes["connection"] = connection
        operation(config, revision)


def test_datetime_defaults_revision_preserves_schema_in_both_directions(
    baseline_engine: Engine,
) -> None:
    previous = "b72e8c913a04"
    head = "cddd162bf081"
    _run(baseline_engine, command.upgrade, previous)

    def schema():
        with baseline_engine.connect() as connection:
            return connection.execute(
                text("SELECT type, name, sql FROM sqlite_master ORDER BY type, name")
            ).all()

    original = schema()
    _run(baseline_engine, command.upgrade, head)
    assert schema() == original
    _run(baseline_engine, command.downgrade, previous)
    assert schema() == original


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


def test_annotation_migration_requires_backfill_and_preserves_identity(
    baseline_engine, tmp_path, monkeypatch
):
    import json
    from io import BytesIO

    from PIL import Image

    from wtbot.annotation_normalization import backfill

    _run(baseline_engine, command.upgrade, "a21d6430c901")
    with baseline_engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO site (pk,family,code,articlepath,created_at) VALUES (1,'wikisource','en','/wiki/$1',CURRENT_TIMESTAMP)"
            )
        )
        c.execute(
            text(
                "INSERT INTO page (pk,site_pk,title,namespace_role,dirty,fetch_status) VALUES (1,1,'Page:Book.pdf/1','page',0,'done')"
            )
        )
        c.execute(
            text(
                "INSERT INTO proofreadpagemeta (page_pk,index_page_pk,source_image_url) VALUES (1,1,'https://example.test/scan.jpg')"
            )
        )
        c.execute(
            text(
                "INSERT INTO scanannotation (pk,page_pk,annotation_id,x,y,width,height,created_at,updated_at) VALUES (1,1,'box',20,60,100,120,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    with pytest.raises(RuntimeError, match="need backfilling"):
        _run(baseline_engine, command.upgrade, "head")
    dump = tmp_path / "dump.json"
    dump.write_text(
        json.dumps(
            [
                dict(
                    pk=1,
                    page_pk=1,
                    annotation_id="box",
                    x=20,
                    y=60,
                    width=100,
                    height=120,
                )
            ]
        )
    )
    image = BytesIO()
    Image.new("RGB", (200, 600)).save(image, format="PNG")
    monkeypatch.setattr(
        "wtbot.annotation_normalization.fetch_image_bytes", lambda url: image.getvalue()
    )
    from pathlib import Path

    backfill(Path(baseline_engine.url.database), dump, apply=True)
    _run(baseline_engine, command.upgrade, "head")
    with baseline_engine.connect() as c:
        assert c.execute(
            text(
                "SELECT pk,page_pk,annotation_id,normalized_x,normalized_y,normalized_width,normalized_height FROM scanannotation"
            )
        ).one() == (1, 1, "box", 0.1, 0.1, 0.5, 0.2)
        columns = {
            row[1]: row[3]
            for row in c.execute(text("PRAGMA table_info(scanannotation)"))
        }
        assert "x" not in columns
        assert all(
            columns[f"normalized_{name}"] == 1 for name in ("x", "y", "width", "height")
        )


def test_namespace_classification_removal_preserves_pages_and_links(baseline_engine):
    _run(baseline_engine, command.upgrade, "b72e8c913a04")
    with baseline_engine.begin() as c:
        c.execute(text("""
            INSERT INTO site (pk, family, code, articlepath, created_at)
            VALUES (1, 'wikisource', 'de', '/wiki/$1', CURRENT_TIMESTAMP)
            """))
        c.execute(text("""
            INSERT INTO namespace
                (pk, site_pk, key, canonical_name, local_name, role, subpages, content)
            VALUES (1, 1, 252, 'Index', 'Index', 'index', 1, 0),
                   (2, 1, 250, 'Page', 'Seite', 'page', 1, 0)
            """))
        c.execute(text("""
            INSERT INTO page
                (pk, site_pk, title, namespace_role, content_model, dirty, fetch_status)
            VALUES (1, 1, 'Index:Book.pdf', 'index', 'proofread-index', 0, 'unfetched'),
                   (2, 1, 'Seite:Book.pdf/1', 'page', 'proofread-page', 1, 'done'),
                   (3, 1, 'Index:Book.pdf/style.css', 'index', 'sanitized-css', 0, 'done'),
                   (4, 1, 'Seite:Book.pdf/data', 'page', 'json', 0, 'done'),
                   (5, 1, 'Datei:Book.pdf', 'file', 'wikitext', 0, 'done'),
                   (6, 1, 'Index:Unknown', 'index', NULL, 0, 'unfetched')
            """))
        c.execute(text("""
            INSERT INTO proofreadpagemeta (page_pk, index_page_pk, page_number)
            VALUES (2, 1, 1)
            """))
    _run(baseline_engine, command.upgrade, "head")
    with baseline_engine.connect() as c:
        assert "namespace_role" not in {
            row[1] for row in c.execute(text("PRAGMA table_info(page)"))
        }
        assert "role" not in {
            row[1] for row in c.execute(text("PRAGMA table_info(namespace)"))
        }
        rows = c.execute(
            text("SELECT pk, namespace_key, content_model, dirty FROM page ORDER BY pk")
        ).all()
        assert rows == [
            (1, 252, "proofread-index", 0),
            (2, 250, "proofread-page", 1),
            (3, 252, "sanitized-css", 0),
            (4, 250, "json", 0),
            (5, 6, "wikitext", 0),
            (6, 252, None, 0),
        ]
        assert c.execute(
            # Renamed at head: the meta row is keyed to the Title (step 2).
            text("SELECT title_pk, index_title_pk FROM proofreadpagemeta")
        ).all() == [(2, 1)]
        assert c.execute(text("PRAGMA foreign_key_check")).all() == []
    _run(baseline_engine, command.downgrade, "b72e8c913a04")
    with baseline_engine.connect() as c:
        assert c.execute(
            text("SELECT namespace_role FROM page ORDER BY pk")
        ).scalars().all() == ["index", "page", "index", "page", "file", "index"]
    _run(baseline_engine, command.upgrade, "head")


# -- the migration runner ----------------------------------------------------
#
# Schema changes in SQLite rebuild tables, and a rebuild drops the old table.
# With foreign keys on, that drop fails whenever anything references the
# table -- which is why earlier migrations avoided rebuilds altogether.
# migration_connection follows SQLite's own procedure instead: keys off, one
# real transaction, a key check over the finished state.


def _parent_and_child(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE parent (pk INTEGER PRIMARY KEY)")
        connection.exec_driver_sql(
            "CREATE TABLE child (pk INTEGER PRIMARY KEY,"
            " parent_pk INTEGER REFERENCES parent(pk))"
        )
        connection.exec_driver_sql("INSERT INTO parent VALUES (1)")
        connection.exec_driver_sql("INSERT INTO child VALUES (1, 1)")


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }


def test_a_referenced_table_can_be_rebuilt(baseline_engine: Engine) -> None:
    _parent_and_child(baseline_engine)

    with migration_connection(baseline_engine) as connection:
        connection.exec_driver_sql(
            "CREATE TABLE parent_new (pk INTEGER PRIMARY KEY, extra TEXT)"
        )
        connection.exec_driver_sql("INSERT INTO parent_new (pk) SELECT pk FROM parent")
        connection.exec_driver_sql("DROP TABLE parent")
        connection.exec_driver_sql("ALTER TABLE parent_new RENAME TO parent")

    with baseline_engine.connect() as connection:
        columns = [
            r[1] for r in connection.exec_driver_sql("PRAGMA table_info(parent)")
        ]
        assert columns == ["pk", "extra"]
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_a_dangling_reference_rolls_back_the_whole_migration(
    baseline_engine: Engine,
) -> None:
    """Including its DDL: pysqlite would otherwise have committed the CREATE
    before the DELETE opened a transaction."""
    _parent_and_child(baseline_engine)

    with pytest.raises(MigrationIntegrityError, match="reference nothing"):
        with migration_connection(baseline_engine) as connection:
            connection.exec_driver_sql("CREATE TABLE should_vanish (x INTEGER)")
            connection.exec_driver_sql("DELETE FROM parent")

    assert "should_vanish" not in _tables(baseline_engine)
    with baseline_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM parent").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


# -- step 1 of the Title/WikiPage split --------------------------------------

BEFORE_TITLE = "76940b0f1272"
TITLE = "5d2a7c41e9b3"


def _seed_pages(engine: Engine) -> None:
    with engine.begin() as connection:
        run = connection.exec_driver_sql
        run(
            "INSERT INTO site (pk, family, code, articlepath, created_at)"
            " VALUES (1, 'ws', 'en', '/wiki/$1', '2026-01-01 00:00:00+00:00')"
        )
        run(
            "INSERT INTO page (pk, site_pk, title, content_model, dirty, fetch_status)"
            " VALUES (7, 1, 'Page:A.djvu/1', 'proofread-page', 0, 'done')"
        )
        run(
            "INSERT INTO page (pk, site_pk, title, content_model, dirty, fetch_status)"
            " VALUES (9, 1, 'Index:A.djvu/styles.css', NULL, 1, 'unfetched')"
        )
        run(
            "INSERT INTO editjournal (page_pk, body, committed, saved_at)"
            " VALUES (9, 'draft', 0, '2026-01-01 00:00:00+00:00')"
        )
        run(
            "INSERT INTO proofreadpagemeta (page_pk, index_page_pk, page_number)"
            " VALUES (7, 9, 1)"
        )


def test_every_existing_page_gets_a_title_with_the_same_pk(
    baseline_engine: Engine,
) -> None:
    _run(baseline_engine, command.upgrade, BEFORE_TITLE)
    _seed_pages(baseline_engine)

    _run(baseline_engine, command.upgrade, TITLE)

    with baseline_engine.connect() as connection:
        run = connection.exec_driver_sql
        assert run(
            "SELECT pk, title, expected_content_model FROM title ORDER BY pk"
        ).all() == [
            (7, "Page:A.djvu/1", "proofread-page"),
            # No model on record: MediaWiki's fallback, not a namespace guess.
            (9, "Index:A.djvu/styles.css", "wikitext"),
        ]
        assert ("title", "pk", "pk") in [
            (r[2], r[3], r[4]) for r in run("PRAGMA foreign_key_list(page)")
        ]
        # page was rebuilt; what referenced it still does.
        assert run("SELECT count(*) FROM editjournal").scalar() == 1
        assert run("SELECT count(*) FROM proofreadpagemeta").scalar() == 1
        assert run("PRAGMA foreign_key_check").all() == []


def test_the_title_step_downgrades_cleanly(baseline_engine: Engine) -> None:
    _run(baseline_engine, command.upgrade, BEFORE_TITLE)
    _seed_pages(baseline_engine)
    _run(baseline_engine, command.upgrade, TITLE)

    _run(baseline_engine, command.downgrade, BEFORE_TITLE)

    assert "title" not in _tables(baseline_engine)
    with baseline_engine.connect() as connection:
        run = connection.exec_driver_sql
        assert run("SELECT count(*) FROM page").scalar() == 2
        assert "title" not in [r[2] for r in run("PRAGMA foreign_key_list(page)")]


# -- step 2: journal, commit and proofread meta keyed to Title ---------------

JOURNAL_TO_TITLE = "8e3f1b6d0a27"


def _foreign_keys(engine: Engine, table: str) -> set[tuple[str, str]]:
    with engine.connect() as connection:
        return {
            (row[3], row[2])  # (column, target table)
            for row in connection.exec_driver_sql(f"PRAGMA foreign_key_list('{table}')")
        }


def _seed_address_rows(engine: Engine) -> None:
    _seed_pages(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            'INSERT INTO "commit" (page_pk, submitted_body, status, created_at)'
            " VALUES (7, 'pushed', 'success', '2026-01-01 00:00:00+00:00')"
        )


def test_journal_commit_and_meta_point_at_titles(baseline_engine: Engine) -> None:
    """Asserts the foreign keys themselves, not just a clean key check: a check
    passes trivially over a table whose keys were silently dropped, which is
    exactly what a first draft of this migration did."""
    _run(baseline_engine, command.upgrade, BEFORE_TITLE)
    _seed_address_rows(baseline_engine)
    _run(baseline_engine, command.upgrade, JOURNAL_TO_TITLE)

    assert _foreign_keys(baseline_engine, "editjournal") == {("title_pk", "title")}
    assert _foreign_keys(baseline_engine, "commit") == {("title_pk", "title")}
    assert _foreign_keys(baseline_engine, "proofreadpagemeta") == {
        ("title_pk", "title"),
        ("index_title_pk", "title"),
    }
    with baseline_engine.connect() as connection:
        run = connection.exec_driver_sql
        # No data moved: each page_pk already was the right title_pk.
        assert run("SELECT title_pk, body FROM editjournal").all() == [(9, "draft")]
        assert run('SELECT title_pk FROM "commit"').all() == [(7,)]
        assert run(
            "SELECT title_pk, index_title_pk, page_number FROM proofreadpagemeta"
        ).all() == [(7, 9, 1)]
        assert run("PRAGMA foreign_key_check").all() == []


def test_journal_commit_and_meta_step_downgrades_cleanly(
    baseline_engine: Engine,
) -> None:
    _run(baseline_engine, command.upgrade, BEFORE_TITLE)
    _seed_address_rows(baseline_engine)
    _run(baseline_engine, command.upgrade, JOURNAL_TO_TITLE)

    _run(baseline_engine, command.downgrade, TITLE)

    assert _foreign_keys(baseline_engine, "editjournal") == {("page_pk", "page")}
    assert _foreign_keys(baseline_engine, "commit") == {("page_pk", "page")}
    assert _foreign_keys(baseline_engine, "proofreadpagemeta") == {
        ("page_pk", "page"),
        ("index_page_pk", "page"),
    }
    with baseline_engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT page_pk, index_page_pk FROM proofreadpagemeta"
        ).all() == [(7, 9)]


def test_the_migrated_schema_matches_the_models(baseline_engine: Engine) -> None:
    """Every migration, end to end, lands exactly on what the models declare.

    Fresh databases are built from the migrations, restores from the models;
    this is what keeps the two the same. It is also the check that catches a
    batch rebuild quietly losing a constraint.
    """
    init_db(baseline_engine)
    with baseline_engine.connect() as connection, warnings.catch_warnings():
        # SQLite cannot reflect the two expression-based unique indexes, so
        # autogenerate skips them (with a warning) rather than comparing them.
        warnings.simplefilter("ignore")
        differences = compare_metadata(
            MigrationContext.configure(connection, opts={"compare_type": True}),
            SQLModel.metadata,
        )
    assert differences == []
