import sqlite3
from pathlib import Path

import pytest
from sqlmodel import Session, SQLModel, create_engine

from wtbot.maintenance.dump import (
    NATURAL_KEYS,
    DatabaseDump,
    Reference,
    read_dump,
    write_dump,
)
from wtbot.model import (
    Content,
    FileBlob,
    IndexLink,
    Page,
    PageLink,
    Revision,
    Site,
    SiteCredential,
    Slot,
)


def make_database(path: Path, offset: int = 0) -> None:
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Site(pk=offset + 1, family="source", code="en"))
        session.add(Site(pk=offset + 2, family="target", code="en"))
        session.add(
            SiteCredential(site_pk=offset + 1, username="bot", password="secret")
        )
        session.add(
            Page(
                pk=offset + 3,
                site_pk=offset + 1,
                title="Index:Book",
                latest_revision_pk=offset + 5,
            )
        )
        session.add(Page(pk=offset + 4, site_pk=offset + 2, title="Index:Book"))
        session.add(Revision(pk=offset + 5, page_pk=offset + 3, revid=123))
        session.add(
            Content(
                pk=offset + 6,
                content_sha1="hash",
                content_model="wikitext",
                text="body",
                size=4,
            )
        )
        session.add(Slot(revision_pk=offset + 5, role="main", content_pk=offset + 6))
        session.add(
            PageLink(
                pk=offset + 7,
                local_page_pk=offset + 3,
                remote_page_pk=offset + 4,
                index_link_pk=offset + 8,
            )
        )
        session.add(IndexLink(pk=offset + 8, page_link_pk=offset + 7))
        session.commit()
    engine.dispose()
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT)")
        connection.execute("INSERT INTO alembic_version VALUES ('legacy')")
        connection.execute("ALTER TABLE site ADD COLUMN legacy_note TEXT")
        connection.execute("UPDATE site SET legacy_note = 'preserved'")


def test_dump_uses_natural_keys_independent_of_source_ids(tmp_path: Path) -> None:
    paths = [tmp_path / "first.db", tmp_path / "second.db"]
    for offset, path in zip((0, 100), paths):
        make_database(path, offset)
    dumps = [read_dump(path) for path in paths]
    assert {table.name for table in dumps[0].tables} == set(NATURAL_KEYS)
    for first, second in zip(dumps[0].tables, dumps[1].tables):
        assert [row.key for row in first.rows] == [row.key for row in second.rows]
        assert [row.references for row in first.rows] == [
            row.references for row in second.rows
        ]
        assert all("pk" not in row.fields for row in first.rows)
    tables = {table.name: table for table in dumps[0].tables}
    page = tables["page"].rows[0]
    assert page.references["site_pk"] == Reference(table="site", key=("source", "en"))
    assert page.references["latest_revision_pk"].table == "revision"
    assert (
        tables["slot"].rows[0].references["revision_pk"].key
        == page.references["latest_revision_pk"].key
    )
    assert tables["site"].rows[0].fields["legacy_note"] == "preserved"
    assert tables["sitecredential"].rows[0].fields["password"] == "secret"


def test_dump_roundtrips_json_and_does_not_modify_source(tmp_path: Path) -> None:
    database, output = tmp_path / "source.db", tmp_path / "dump.json"
    make_database(database)
    original = database.read_bytes()
    dump = write_dump(database, output)
    assert DatabaseDump.model_validate_json(output.read_bytes()) == dump
    assert database.read_bytes() == original
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        write_dump(database, output)
    with pytest.raises(FileExistsError):
        write_dump(database, database)
    assert database.read_bytes() == original


def test_dump_rejects_missing_targets_without_writing_output(tmp_path: Path) -> None:
    database, output = tmp_path / "source.db", tmp_path / "dump.json"
    make_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE page SET latest_revision_pk = 999")
    with pytest.raises(ValueError, match="Unresolved reference to revision"):
        write_dump(database, output)
    assert not output.exists()


def test_dump_rejects_ambiguous_natural_keys(tmp_path: Path) -> None:
    database = tmp_path / "source.db"
    make_database(database)
    engine = create_engine(f"sqlite:///{database}")
    with Session(engine) as session:
        session.add_all([FileBlob(page_pk=3), FileBlob(page_pk=3)])
        session.commit()
    engine.dispose()
    with pytest.raises(ValueError, match="Duplicate natural key in fileblob"):
        read_dump(database)


def test_missing_source_is_not_created(tmp_path: Path) -> None:
    database = tmp_path / "missing.db"
    with pytest.raises(sqlite3.OperationalError):
        read_dump(database)
    assert not database.exists()
