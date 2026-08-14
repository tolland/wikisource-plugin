import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
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
            for table in (
                "page",
                "revision",
                "slot",
                "content",
                "proofreadpagemeta",
            )
        }
    # The backfill materializes the previously title-only Index identity.
    assert counts == {
        "page": 2,
        "revision": 1,
        "slot": 1,
        "content": 1,
        "proofreadpagemeta": 1,
    }


def test_proofread_meta_copy_is_inspectable_before_old_table_drop(
    populated_engine,
) -> None:
    _upgrade(populated_engine, "2f6a8c1d9e40")

    with Session(populated_engine) as session:
        old = session.exec(
            text("SELECT page_pk, index_title, page_number FROM pagemeta")
        ).one()
        new = session.exec(
            text(
                "SELECT m.page_pk, i.title, m.page_number"
                " FROM proofreadpagemeta m JOIN page i ON i.pk = m.index_page_pk"
            )
        ).one()
    assert old == new == (1, "Index:Work.djvu", 1)


def test_index_assets_are_not_misclassified_as_proofread_metadata(
    populated_engine,
) -> None:
    with Session(populated_engine) as session:
        session.exec(
            text(
                "INSERT INTO page (pk, site_pk, title, namespace_role,"
                " content_model, dirty, fetch_status)"
                " VALUES (2, 1, 'Index:Work.djvu/styles.css', 'index',"
                " 'sanitized-css', 0, 'done')"
            )
        )
        session.exec(
            text(
                "INSERT INTO pagemeta (pk, page_pk, index_title)"
                " VALUES (2, 2, 'Index:Work.djvu')"
            )
        )
        session.commit()

    _upgrade(populated_engine, "2f6a8c1d9e40")

    with Session(populated_engine) as session:
        assert session.exec(text("SELECT count(*) FROM pagemeta")).one()[0] == 2
        assert (
            session.exec(text("SELECT count(*) FROM proofreadpagemeta")).one()[0] == 1
        )


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


def test_the_migrated_revisionlink_rejects_a_reversed_pair(populated_engine) -> None:
    """The unordered-pair guarantee has to survive the migration path, not just
    ``create_all``. A schema where a fresh database enforces it and a migrated
    one does not is worse than neither."""
    _upgrade(populated_engine, "head")

    with Session(populated_engine) as session:
        session.exec(
            text(
                "INSERT INTO page (pk, site_pk, title, namespace_role, dirty,"
                " fetch_status) VALUES (3, 1, 'Page:Work.djvu/1 (upstream)',"
                " 'page', 0, 'done')"
            )
        )
        session.exec(
            text(
                "INSERT INTO revision (pk, page_pk, revid, minor, observed_at)"
                " VALUES (2, 3, 9, 0, CURRENT_TIMESTAMP)"
            )
        )
        session.exec(
            text(
                "INSERT INTO revisionlink (local_revision_pk, remote_revision_pk,"
                " origin) VALUES (1, 2, 'copy')"
            )
        )
        session.commit()

        with pytest.raises(IntegrityError, match="uq_revisionlink_pair"):
            session.exec(
                text(
                    "INSERT INTO revisionlink (local_revision_pk,"
                    " remote_revision_pk, origin) VALUES (2, 1, 'manual')"
                )
            )
            session.commit()


def test_dropping_revisionlink_leaves_the_revisions_it_referenced(
    populated_engine,
) -> None:
    """`revisionlink` points at `revision`, so its downgrade is the direction
    that can go wrong: a rebuild of `revision` would fail with `slot` rows
    referencing it. Seeded after the upgrade because the table does not exist
    before it."""
    _upgrade(populated_engine, "head")
    with Session(populated_engine) as session:
        session.exec(
            text(
                "INSERT INTO page (pk, site_pk, title, namespace_role, dirty,"
                " fetch_status) VALUES (3, 1, 'Page:Work.djvu/1 (upstream)',"
                " 'page', 0, 'done')"
            )
        )
        session.exec(
            text(
                "INSERT INTO revision (pk, page_pk, revid, minor, observed_at)"
                " VALUES (2, 3, 9, 0, CURRENT_TIMESTAMP)"
            )
        )
        session.exec(
            text(
                "INSERT INTO revisionlink (local_revision_pk, remote_revision_pk,"
                " origin) VALUES (1, 2, 'copy')"
            )
        )
        session.commit()

    _downgrade(populated_engine, REVISION_STORE)

    with Session(populated_engine) as session:
        assert session.exec(text("SELECT count(*) FROM revision")).one()[0] == 2
        assert session.exec(text("SELECT count(*) FROM slot")).one()[0] == 1


def test_comparable_sha1_is_backfilled_from_the_stored_text(populated_engine) -> None:
    """The digest is a pure function of text and content model, so existing
    rows are computed rather than left null -- otherwise every body fetched
    before the upgrade would keep falling back to a parse forever."""
    from wtbot.content_model import comparable_sha1

    same_words_other_user = (
        '<noinclude><pagequality level="3" user="Them" /></noinclude>Words'
        "<noinclude></noinclude>"
    )
    with Session(populated_engine) as session:
        session.exec(
            text(
                "INSERT INTO content (pk, content_sha1, content_model, text, size)"
                " VALUES (2, 'def', 'proofread-page', :text, 60)"
            ).bindparams(text=same_words_other_user)
        )
        session.commit()

    _upgrade(populated_engine, "head")

    with Session(populated_engine) as session:
        digests = dict(
            session.exec(text("SELECT pk, comparable_sha1 FROM content")).all()
        )
    assert digests[1] == comparable_sha1("body", "proofread-page")
    assert digests[2] == comparable_sha1(same_words_other_user, "proofread-page")


def test_downgrade_also_survives_referenced_rows(populated_engine) -> None:
    """The reverse direction rebuilds nothing either -- a downgrade that drops
    `page` would fail on the eleven tables referencing page.pk."""
    _upgrade(populated_engine, "head")
    _downgrade(populated_engine, REVISION_STORE)

    with Session(populated_engine) as session:
        # Downgrading leaves the harmless Index placeholder created by the
        # keyed backfill; it cannot be identified safely as migration-owned.
        assert session.exec(text("SELECT count(*) FROM page")).one()[0] == 2
        assert session.exec(text("SELECT count(*) FROM pagemeta")).one()[0] == 1
