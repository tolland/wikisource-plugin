import pytest
from alembic import command
from sqlalchemy import text
from sqlmodel import Session

from wtbot.db import alembic_config, create_db_engine

"""Migrations must survive a database that has rows in it.

An empty database hides a whole class of SQLite migration bug. ``PRAGMA
foreign_keys=ON`` is set on every connection (see wtbot.db), and alembic's
``batch_alter_table`` implements column changes by rebuilding the table --
create, copy, ``DROP TABLE``, rename. On an empty database the drop succeeds
because nothing references the table; with one referencing row it fails with
``FOREIGN KEY constraint failed``.

That is not hypothetical: dropping ``revision.remote_sha1`` via batch mode
failed exactly this way against a real database, having passed against a fresh
one. These tests run the migrations over populated tables so the next such
change is caught here rather than on someone's data.
"""

# The revision store landed here; anything after it must cope with its rows.
REVISION_STORE = "d4a7b1e6c5f2"

SEED = [
    "INSERT INTO site (pk, family, code, articlepath, created_at)"
    " VALUES (1, 'wikisource', 'en', '/wiki/$1', CURRENT_TIMESTAMP)",
    "INSERT INTO page (pk, site_pk, title, namespace_role, dirty, fetch_status)"
    " VALUES (1, 1, 'Page:Work.djvu/1', 'page', 0, 'done')",
    "INSERT INTO content (pk, content_sha1, content_model, text, size)"
    " VALUES (1, 'abc', 'proofread-page', 'body', 4)",
    "INSERT INTO revision (pk, page_pk, revid, minor, observed_at)"
    " VALUES (1, 1, 7, 0, CURRENT_TIMESTAMP)",
    "INSERT INTO slot (revision_pk, role, content_pk) VALUES (1, 'main', 1)",
    # A referrer into page.pk, so a rebuild of `page` would fail too.
    "INSERT INTO pagemeta (pk, page_pk, index_title, page_number)"
    " VALUES (1, 1, 'Index:Work.djvu', 1)",
]


def _upgrade(engine, target: str) -> None:
    cfg = alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, target)


def _downgrade(engine, target: str) -> None:
    cfg = alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, target)


@pytest.fixture
def populated_engine(tmp_path):
    """A database at the revision-store migration, with rows in every table
    the later migrations touch."""
    engine = create_db_engine(f"sqlite:///{tmp_path / 'migrate.db'}")
    _upgrade(engine, REVISION_STORE)
    with Session(engine) as session:
        for statement in SEED:
            session.exec(text(statement))
        session.commit()
    return engine


def test_upgrade_to_head_survives_referenced_rows(populated_engine) -> None:
    _upgrade(populated_engine, "head")

    with Session(populated_engine) as session:
        counts = {
            table: session.exec(text(f"SELECT count(*) FROM {table}")).one()[0]
            for table in ("page", "revision", "slot", "content", "pagemeta")
        }
    assert counts == {"page": 1, "revision": 1, "slot": 1, "content": 1, "pagemeta": 1}


def test_the_chain_still_joins_after_upgrading(populated_engine) -> None:
    """Row counts alone would not catch a rebuild that renumbered primary keys
    and left the foreign keys pointing at nothing."""
    _upgrade(populated_engine, "head")

    with Session(populated_engine) as session:
        body = session.exec(
            text(
                "SELECT c.text FROM page p"
                " JOIN revision r ON r.page_pk = p.pk"
                " JOIN slot s ON s.revision_pk = r.pk"
                " JOIN content c ON c.pk = s.content_pk"
            )
        ).one()[0]
    assert body == "body"


def test_dropping_remotelink_leaves_the_revisions_it_referenced(
    populated_engine,
) -> None:
    """`remotelink` points at `revision`, so its downgrade is the direction
    that can go wrong: a rebuild of `revision` would fail with `slot` rows
    referencing it. Seeded after the upgrade because the table does not exist
    before it."""
    _upgrade(populated_engine, "head")
    with Session(populated_engine) as session:
        session.exec(
            text(
                "INSERT INTO page (pk, site_pk, title, namespace_role, dirty,"
                " fetch_status) VALUES (2, 1, 'Page:Work.djvu/1 (upstream)',"
                " 'page', 0, 'done')"
            )
        )
        session.exec(
            text(
                "INSERT INTO revision (pk, page_pk, revid, minor, observed_at)"
                " VALUES (2, 2, 9, 0, CURRENT_TIMESTAMP)"
            )
        )
        session.exec(
            text(
                "INSERT INTO remotelink (local_revision_pk, remote_revision_pk,"
                " origin) VALUES (1, 2, 'copy')"
            )
        )
        session.commit()

    _downgrade(populated_engine, REVISION_STORE)

    with Session(populated_engine) as session:
        assert session.exec(text("SELECT count(*) FROM revision")).one()[0] == 2
        assert session.exec(text("SELECT count(*) FROM slot")).one()[0] == 1


def test_downgrade_also_survives_referenced_rows(populated_engine) -> None:
    """The reverse direction rebuilds nothing either -- a downgrade that drops
    `page` would fail on the eleven tables referencing page.pk."""
    _upgrade(populated_engine, "head")
    _downgrade(populated_engine, REVISION_STORE)

    with Session(populated_engine) as session:
        assert session.exec(text("SELECT count(*) FROM page")).one()[0] == 1
        assert session.exec(text("SELECT count(*) FROM pagemeta")).one()[0] == 1
