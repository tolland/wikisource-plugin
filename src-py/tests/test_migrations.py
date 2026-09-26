import warnings

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
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

    # Pinned to the migration under test: later steps reshape promotionbatch
    # (b41d8e2c7f60 reduces it to its two ends), and they have their own tests.
    _run(baseline_engine, command.upgrade, "f19c2d4a7b31")

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
    # Pinned to the migration under test: later steps rename scanannotation's
    # page_pk (e5f2a8d1c349), and they have their own tests.
    with pytest.raises(RuntimeError, match="need backfilling"):
        _run(baseline_engine, command.upgrade, "a21d6430c902")
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
    _run(baseline_engine, command.upgrade, "a21d6430c902")
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
    _run(baseline_engine, command.upgrade, INDEX_META_AND_PAIRS_ON_TITLE)
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
            # Renamed by then: the meta row is keyed to the Title (step 2).
            text("SELECT title_pk, index_title_pk FROM proofreadpagemeta")
        ).all() == [(2, 1)]
        assert c.execute(text("PRAGMA foreign_key_check")).all() == []
    _run(baseline_engine, command.downgrade, "b72e8c913a04")
    with baseline_engine.connect() as c:
        assert c.execute(
            text("SELECT namespace_role FROM page ORDER BY pk")
        ).scalars().all() == ["index", "page", "index", "page", "file", "index"]
    _run(baseline_engine, command.upgrade, INDEX_META_AND_PAIRS_ON_TITLE)


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


# -- step 2: PromotionBatch reduced to its two ends ---------------------------

BATCH_TWO_ENDS = "b41d8e2c7f60"
_T = "'2026-01-01 00:00:00+00:00'"


def test_a_batch_keeps_its_ends_and_a_create_gets_its_target_title(
    baseline_engine: Engine,
) -> None:
    _run(baseline_engine, command.upgrade, JOURNAL_TO_TITLE)
    with baseline_engine.begin() as connection:
        run = connection.exec_driver_sql
        run(
            "INSERT INTO site (pk, family, code, articlepath, created_at) VALUES"
            f" (1, 'up', 'en', '/wiki/$1', {_T}), (2, 'down', 'en', '/wiki/$1', {_T})"
        )
        for pk, site, title in ((7, 1, "P/1"), (8, 2, "P/1"), (9, 1, "P/2")):
            run(
                "INSERT INTO title (pk, site_pk, title, expected_content_model)"
                f" VALUES ({pk}, {site}, '{title}', 'proofread-page')"
            )
            run(
                "INSERT INTO page (pk, site_pk, title, content_model, dirty,"
                f" fetch_status) VALUES ({pk}, {site}, '{title}', 'proofread-page',"
                " 0, 'done')"
            )
        # An update (the target page exists) and a create (it does not).
        for pk, source, target, name in ((1, 7, 8, "P/1"), (2, 9, "NULL", "P/2")):
            run(
                "INSERT INTO promotionbatch (pk, source_site_pk, target_site_pk,"
                " source_page_pk, target_page_pk, source_title, target_title,"
                f" status, created_at) VALUES ({pk}, 1, 2, {source}, {target},"
                f" '{name}', '{name}', 'draft', {_T})"
            )

    _run(baseline_engine, command.upgrade, BATCH_TWO_ENDS)

    assert _foreign_keys(baseline_engine, "promotionbatch") == {
        ("source_page_pk", "page"),
        ("target_title_pk", "title"),
        ("anchor_link_pk", "revisionlink"),
    }
    with baseline_engine.connect() as connection:
        run = connection.exec_driver_sql
        rows = run("""
            SELECT b.pk, b.source_page_pk, t.site_pk, t.title,
                   t.expected_content_model,
                   EXISTS (SELECT 1 FROM page p WHERE p.pk = t.pk)
            FROM promotionbatch b JOIN title t ON t.pk = b.target_title_pk
            ORDER BY b.pk
            """).all()
        assert run("PRAGMA foreign_key_check").all() == []
    assert rows == [
        (1, 7, 2, "P/1", "proofread-page", 1),
        # The create's target had no page, so it gets a title at that address,
        # expecting the source's content model -- and still no page.
        (2, 9, 2, "P/2", "proofread-page", 0),
    ]


def test_the_two_ends_step_downgrades_with_its_copies_refilled(
    baseline_engine: Engine,
) -> None:
    # Seeded in the pre-title shape, which is what _seed_address_rows writes.
    _run(baseline_engine, command.upgrade, BEFORE_TITLE)
    _seed_address_rows(baseline_engine)
    with baseline_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO promotionbatch (pk, source_site_pk, target_site_pk,"
            " source_page_pk, target_page_pk, source_title, target_title,"
            f" status, created_at) VALUES (1, 1, 1, 7, 9, 'Page:A.djvu/1',"
            f" 'Index:A.djvu/styles.css', 'draft', {_T})"
        )
    _run(baseline_engine, command.upgrade, BATCH_TWO_ENDS)

    _run(baseline_engine, command.downgrade, JOURNAL_TO_TITLE)

    with baseline_engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT source_site_pk, target_site_pk, target_page_pk, source_title,"
            " target_title, page_number FROM promotionbatch"
        ).all() == [(1, 1, 9, "Page:A.djvu/1", "Index:A.djvu/styles.css", 1)]


# -- step 2: IndexLink shares PageLink's key ---------------------------------

WORK_SHARES_KEY = "d7a3c9e5b184"


def _seed_work(engine: Engine) -> None:
    """A tracked work (pairing 50 of two indexes, tracked as work 3) with one
    page pair under it, pointed at the work the old way."""
    with engine.begin() as connection:
        run = connection.exec_driver_sql
        run(
            "INSERT INTO site (pk, family, code, articlepath, created_at) VALUES"
            f" (1, 'up', 'en', '/wiki/$1', {_T}), (2, 'down', 'en', '/wiki/$1', {_T})"
        )
        rows = (
            (10, 1, "Index:B.djvu", "proofread-index"),
            (20, 2, "Index:B.djvu", "proofread-index"),
            (11, 1, "Page:B.djvu/1", "proofread-page"),
            (21, 2, "Page:B.djvu/1", "proofread-page"),
        )
        for pk, site, title, model in rows:
            run(
                "INSERT INTO title (pk, site_pk, title, expected_content_model)"
                f" VALUES ({pk}, {site}, '{title}', '{model}')"
            )
            run(
                "INSERT INTO page (pk, site_pk, title, content_model, dirty,"
                f" fetch_status) VALUES ({pk}, {site}, '{title}', '{model}', 0,"
                " 'done')"
            )
        run(
            "INSERT INTO proofreadpagemeta (title_pk, index_title_pk, page_number)"
            " VALUES (11, 10, 1), (21, 20, 1)"
        )
        run(
            "INSERT INTO pagelink (pk, local_page_pk, remote_page_pk, origin,"
            f" created_at) VALUES (50, 10, 20, 'manual', {_T})"
        )
        run(
            f"INSERT INTO indexlink (pk, page_link_pk, created_at) VALUES (3, 50, {_T})"
        )
        run(
            "INSERT INTO pagelink (pk, local_page_pk, remote_page_pk, index_link_pk,"
            f" origin, created_at) VALUES (51, 11, 21, 3, 'title_match', {_T})"
        )


def test_a_work_takes_its_pairings_key_and_pairs_lose_their_pointer(
    baseline_engine: Engine,
) -> None:
    _run(baseline_engine, command.upgrade, BATCH_TWO_ENDS)
    _seed_work(baseline_engine)

    _run(baseline_engine, command.upgrade, WORK_SHARES_KEY)

    assert _foreign_keys(baseline_engine, "indexlink") == {("pk", "pagelink")}
    assert _foreign_keys(baseline_engine, "pagelink") == {
        ("local_page_pk", "page"),
        ("remote_page_pk", "page"),
    }
    with baseline_engine.begin() as connection:
        run = connection.exec_driver_sql
        assert run("SELECT pk FROM indexlink").all() == [(50,)]
        assert "index_link_pk" not in {
            row[1] for row in run("PRAGMA table_info(pagelink)")
        }
        assert run("PRAGMA foreign_key_check").all() == []
        # The rebuild restated the expression index batch mode cannot see: a
        # pairing asserted the other way round is still refused.
        with pytest.raises(IntegrityError):
            run(
                "INSERT INTO pagelink (pk, local_page_pk, remote_page_pk, origin,"
                f" created_at) VALUES (52, 21, 11, 'manual', {_T})"
            )


def test_the_shared_key_step_downgrades_with_pointers_restored(
    baseline_engine: Engine,
) -> None:
    _run(baseline_engine, command.upgrade, BATCH_TWO_ENDS)
    _seed_work(baseline_engine)
    _run(baseline_engine, command.upgrade, WORK_SHARES_KEY)

    _run(baseline_engine, command.downgrade, BATCH_TWO_ENDS)

    with baseline_engine.connect() as connection:
        run = connection.exec_driver_sql
        assert run("SELECT pk, page_link_pk FROM indexlink").all() == [(50, 50)]
        assert run("SELECT pk, index_link_pk FROM pagelink ORDER BY pk").all() == [
            (50, None),
            (51, 50),
        ]
        assert run("PRAGMA foreign_key_check").all() == []


# -- step 2: annotations keyed to Title --------------------------------------

ANNOTATIONS_TO_TITLE = "e5f2a8d1c349"
_ANNOTATION_TABLES = ("scanannotation", "boxrangelink", "texttargetanchor")


def _seed_annotations(engine: Engine) -> None:
    with engine.begin() as connection:
        run = connection.exec_driver_sql
        run(
            "INSERT INTO site (pk, family, code, articlepath, created_at)"
            f" VALUES (1, 'up', 'en', '/wiki/$1', {_T})"
        )
        run(
            "INSERT INTO title (pk, site_pk, title, expected_content_model)"
            " VALUES (7, 1, 'Page:A/1', 'proofread-page')"
        )
        run(
            "INSERT INTO page (pk, site_pk, title, content_model, dirty, fetch_status)"
            " VALUES (7, 1, 'Page:A/1', 'proofread-page', 0, 'done')"
        )
        run(
            "INSERT INTO scanannotation (page_pk, annotation_id, category, created_at,"
            " updated_at, normalized_x, normalized_y, normalized_width,"
            f" normalized_height) VALUES (7, 'box-1', 'unknown', {_T}, {_T},"
            " 0.1, 0.1, 0.2, 0.2)"
        )
        run(
            "INSERT INTO boxrangelink (page_pk, box_annotation_id,"
            " range_annotation_id, created_at, updated_at)"
            f" VALUES (7, 'box-1', 'range-1', {_T}, {_T})"
        )
        run(
            "INSERT INTO texttargetanchor (page_pk, annotation_id, text_start,"
            f" text_end, updated_at) VALUES (7, 'range-1', 0, 5, {_T})"
        )


def test_annotations_point_at_titles(baseline_engine: Engine) -> None:
    _run(baseline_engine, command.upgrade, WORK_SHARES_KEY)
    _seed_annotations(baseline_engine)

    _run(baseline_engine, command.upgrade, ANNOTATIONS_TO_TITLE)

    with baseline_engine.connect() as connection:
        run = connection.exec_driver_sql
        for table in _ANNOTATION_TABLES:
            assert _foreign_keys(baseline_engine, table) == {("title_pk", "title")}
            assert run(f"SELECT title_pk FROM {table}").all() == [(7,)]
            # The unique constraint followed the rename rather than being lost.
            ddl = run(f"SELECT sql FROM sqlite_master WHERE name = '{table}'").scalar()
            assert "UNIQUE (title_pk," in ddl
        assert run("PRAGMA foreign_key_check").all() == []


def test_the_annotation_step_downgrades_cleanly(baseline_engine: Engine) -> None:
    _run(baseline_engine, command.upgrade, WORK_SHARES_KEY)
    _seed_annotations(baseline_engine)
    _run(baseline_engine, command.upgrade, ANNOTATIONS_TO_TITLE)

    _run(baseline_engine, command.downgrade, WORK_SHARES_KEY)

    with baseline_engine.connect() as connection:
        for table in _ANNOTATION_TABLES:
            assert _foreign_keys(baseline_engine, table) == {("page_pk", "page")}
            assert connection.exec_driver_sql(f"SELECT page_pk FROM {table}").all() == [
                (7,)
            ]


# -- step 2: Transclusion and FileMeta dropped, to be redesigned -------------

TABLES_DROPPED = "f8c0a6e2d493"


def test_transclusion_and_filemeta_are_dropped_and_come_back_empty(
    baseline_engine: Engine,
) -> None:
    # Seeded in the shape _seed_annotations writes: a site and a page to cite.
    _run(baseline_engine, command.upgrade, WORK_SHARES_KEY)
    _seed_annotations(baseline_engine)
    _run(baseline_engine, command.upgrade, ANNOTATIONS_TO_TITLE)
    with baseline_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO filemeta (page_pk, origin) VALUES (7, 'paste')"
        )

    _run(baseline_engine, command.upgrade, TABLES_DROPPED)
    assert not {"transclusion", "filemeta"} & _tables(baseline_engine)

    _run(baseline_engine, command.downgrade, ANNOTATIONS_TO_TITLE)
    assert {"transclusion", "filemeta"} <= _tables(baseline_engine)
    with baseline_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM filemeta").scalar() == 0


# -- step 2: IndexMeta keyed by its title; PageLink sides are titles ---------

INDEX_META_AND_PAIRS_ON_TITLE = "a9d4b7e1f026"


def _seed_index_meta_and_pairing(engine: Engine) -> None:
    with engine.begin() as connection:
        run = connection.exec_driver_sql
        run(
            "INSERT INTO site (pk, family, code, articlepath, created_at) VALUES"
            f" (1, 'up', 'en', '/wiki/$1', {_T}), (2, 'down', 'en', '/wiki/$1', {_T})"
        )
        for pk, site in ((10, 1), (20, 2)):
            run(
                "INSERT INTO title (pk, site_pk, title, expected_content_model)"
                f" VALUES ({pk}, {site}, 'Index:B.djvu', 'proofread-index')"
            )
            run(
                "INSERT INTO page (pk, site_pk, title, content_model, dirty,"
                f" fetch_status) VALUES ({pk}, {site}, 'Index:B.djvu',"
                " 'proofread-index', 0, 'done')"
            )
        # A surrogate pk (5) unlike the page's (10), so re-keying shows.
        run(
            "INSERT INTO indexmeta (pk, page_pk, site_pk, short_name, page_count)"
            " VALUES (5, 10, 1, 'B', 42)"
        )
        run(
            "INSERT INTO pagelink (pk, local_page_pk, remote_page_pk, origin,"
            f" created_at) VALUES (50, 10, 20, 'manual', {_T})"
        )
        run(f"INSERT INTO indexlink (pk, created_at) VALUES (50, {_T})")


def test_index_meta_takes_its_titles_key_and_pairs_point_at_titles(
    baseline_engine: Engine,
) -> None:
    _run(baseline_engine, command.upgrade, TABLES_DROPPED)
    _seed_index_meta_and_pairing(baseline_engine)

    _run(baseline_engine, command.upgrade, INDEX_META_AND_PAIRS_ON_TITLE)

    assert _foreign_keys(baseline_engine, "indexmeta") == {
        ("title_pk", "title"),
        ("site_pk", "site"),
    }
    assert _foreign_keys(baseline_engine, "pagelink") == {
        ("local_page_pk", "title"),
        ("remote_page_pk", "title"),
    }
    with baseline_engine.begin() as connection:
        run = connection.exec_driver_sql
        assert run("SELECT * FROM indexmeta").all() == [(10, 1, "B", 42)]
        assert run("PRAGMA foreign_key_check").all() == []
        with pytest.raises(IntegrityError):  # uq_pagelink_pair survived
            run(
                "INSERT INTO pagelink (pk, local_page_pk, remote_page_pk, origin,"
                f" created_at) VALUES (51, 20, 10, 'manual', {_T})"
            )


def test_index_meta_and_pairs_step_downgrades_cleanly(baseline_engine: Engine) -> None:
    _run(baseline_engine, command.upgrade, TABLES_DROPPED)
    _seed_index_meta_and_pairing(baseline_engine)
    _run(baseline_engine, command.upgrade, INDEX_META_AND_PAIRS_ON_TITLE)

    _run(baseline_engine, command.downgrade, TABLES_DROPPED)

    assert _foreign_keys(baseline_engine, "pagelink") == {
        ("local_page_pk", "page"),
        ("remote_page_pk", "page"),
    }
    with baseline_engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT page_pk, site_pk, short_name, page_count FROM indexmeta"
        ).all() == [(10, 1, "B", 42)]


# -- step 2: the address's columns move from page to title --------------------

ADDRESS_COLUMNS_ON_TITLE = "b3e7c2f9a15d"


def _columns(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return {
            row[1] for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
        }


def _seed_address_columns(engine: Engine) -> None:
    """A fetched page (10), a fetched-and-absent placeholder with a local save
    (11), and a bare title with no page behind it (12)."""
    with engine.begin() as connection:
        run = connection.exec_driver_sql
        run(
            "INSERT INTO site (pk, family, code, articlepath, created_at)"
            f" VALUES (1, 'up', 'en', '/wiki/$1', {_T})"
        )
        for pk, title, model in (
            (10, "Index:B.djvu", "proofread-index"),
            (11, "Page:B.djvu/1", "proofread-page"),
            (12, "Page:B.djvu/2", "proofread-page"),
        ):
            run(
                "INSERT INTO title (pk, site_pk, title, expected_content_model)"
                f" VALUES ({pk}, 1, '{title}', '{model}')"
            )
        run(
            "INSERT INTO page (pk, site_pk, title, namespace_key, content_model,"
            " dirty, fetch_status, fetch_error) VALUES"
            " (10, 1, 'Index:B.djvu', 252, 'proofread-index', 0, 'done', NULL),"
            " (11, 1, 'Page:B.djvu/1', NULL, 'proofread-page', 1, 'done', 'x')"
        )


def test_the_address_columns_move_to_title(baseline_engine: Engine) -> None:
    _run(baseline_engine, command.upgrade, INDEX_META_AND_PAIRS_ON_TITLE)
    _seed_address_columns(baseline_engine)

    _run(baseline_engine, command.upgrade, ADDRESS_COLUMNS_ON_TITLE)

    assert not {"namespace_key", "dirty", "fetch_status", "fetch_error"} & _columns(
        baseline_engine, "page"
    )
    assert "history_complete_from_revid" in _columns(baseline_engine, "page")
    with baseline_engine.begin() as connection:
        run = connection.exec_driver_sql
        assert run(
            "SELECT pk, namespace_key, fetch_status, dirty FROM title ORDER BY pk"
        ).all() == [
            (10, 252, "done", 0),
            (11, None, "done", 1),
            (12, None, "unfetched", 0),
        ]
        assert run("PRAGMA foreign_key_check").all() == []
        # A title inserted without them takes the defaults.
        run(
            "INSERT INTO title (pk, site_pk, title, expected_content_model)"
            " VALUES (13, 1, 'Page:B.djvu/3', 'proofread-page')"
        )
        assert run("SELECT fetch_status, dirty FROM title WHERE pk = 13").one() == (
            "unfetched",
            0,
        )


def test_the_address_columns_step_downgrades_cleanly(baseline_engine: Engine) -> None:
    _run(baseline_engine, command.upgrade, INDEX_META_AND_PAIRS_ON_TITLE)
    _seed_address_columns(baseline_engine)
    _run(baseline_engine, command.upgrade, ADDRESS_COLUMNS_ON_TITLE)

    _run(baseline_engine, command.downgrade, INDEX_META_AND_PAIRS_ON_TITLE)

    assert not {"namespace_key", "dirty", "fetch_status"} & _columns(
        baseline_engine, "title"
    )
    with baseline_engine.connect() as connection:
        # fetch_error was never written; it comes back empty.
        assert connection.exec_driver_sql(
            "SELECT pk, namespace_key, fetch_status, dirty, fetch_error FROM page"
            " ORDER BY pk"
        ).all() == [(10, 252, "done", 0, None), (11, None, "done", 1, None)]
