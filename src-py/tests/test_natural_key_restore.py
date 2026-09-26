import json
import sqlite3
from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from test_natural_key_dump import make_database

from wtbot.db import alembic_config
from wtbot.maintenance.dump import OMITTED_TABLES, read_dump, write_dump
from wtbot.maintenance.restore import restore_dump


def test_restore_roundtrip_with_new_ids_and_named_constraints(tmp_path: Path) -> None:
    original, archive, rebuilt = (
        tmp_path / name for name in ("source.db", "dump.json", "rebuilt.db")
    )
    make_database(original, offset=100)
    before = write_dump(original, archive)
    result = restore_dump(
        archive, rebuilt, ignore_columns=frozenset({"site.legacy_note"})
    )
    after = read_dump(rebuilt)
    assert result.rows == sum(len(table.rows) for table in before.tables)
    assert result.tables == 18
    for table in before.tables:
        for row in table.rows:
            row.fields.pop("legacy_note", None)
    assert before.tables == after.tables
    assert before.external_files == after.external_files
    assert rebuilt.stat().st_mode & 0o777 == 0o600
    with sqlite3.connect(rebuilt) as connection:
        assert connection.execute("SELECT pk FROM site ORDER BY pk").fetchall() == [
            (1,),
            (2,),
        ]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        # Every page came back sharing its pk with the title at its address,
        # and the revision that cites the page cites that same number.
        assert (
            connection.execute("""
            SELECT count(*) FROM page p JOIN title t
              ON t.pk = p.pk AND t.site_pk = p.site_pk AND t.title = p.title
            """).fetchone()
            == connection.execute("SELECT count(*) FROM page").fetchone()
        )
        assert connection.execute("""
            SELECT count(*) FROM revision r JOIN title t ON t.pk = r.page_pk
            """).fetchone() == (1,)
        for name in OMITTED_TABLES:
            assert connection.execute(f'SELECT count(*) FROM "{name}"').fetchone() == (
                0,
            )
        ddl = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='indexlink'"
        ).fetchone()[0]
        assert "fk_indexlink_pk_pagelink" in ddl
        assert (
            connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == ScriptDirectory.from_config(alembic_config()).get_current_head()
        )


def test_restore_refuses_to_discard_legacy_fields_implicitly(tmp_path: Path) -> None:
    original, archive, rebuilt = (
        tmp_path / name for name in ("source.db", "dump.json", "rebuilt.db")
    )
    make_database(original)
    write_dump(original, archive)
    with pytest.raises(ValueError, match="Unknown legacy column: site.legacy_note"):
        restore_dump(archive, rebuilt)
    assert not rebuilt.exists()


def test_restore_preserves_existing_destination(tmp_path: Path) -> None:
    destination = tmp_path / "existing.db"
    destination.write_bytes(b"do not overwrite")
    with pytest.raises(FileExistsError):
        restore_dump(tmp_path / "missing.json", destination)
    assert destination.read_bytes() == b"do not overwrite"


@pytest.mark.parametrize(
    "damage", ["dangling", "wrong_target", "key_mismatch", "duplicate", "missing_table"]
)
def test_restore_rejects_invalid_archives(tmp_path: Path, damage: str) -> None:
    original, archive, rebuilt = (
        tmp_path / name for name in ("source.db", "dump.json", "rebuilt.db")
    )
    make_database(original)
    dump = write_dump(original, archive)
    tables = {table.name: table for table in dump.tables}
    if damage == "dangling":
        tables["page"].rows[0].references["latest_revision_pk"].key = ("missing",)
    elif damage == "wrong_target":
        tables["page"].rows[0].references["latest_revision_pk"].table = "site"
    elif damage == "key_mismatch":
        tables["site"].rows[0].fields["family"] = "mismatch"
    elif damage == "duplicate":
        tables["site"].rows.append(tables["site"].rows[0])
    else:
        # By name, and one no legacy upgrade can supply: a dump missing
        # `title` is an old dump, and the restore rightly completes it.
        dump.tables[:] = [table for table in dump.tables if table.name != "revision"]
    archive.write_text(dump.model_dump_json())
    with pytest.raises(ValueError):
        restore_dump(archive, rebuilt, ignore_columns=frozenset({"site.legacy_note"}))
    assert not rebuilt.exists()
    assert not list(tmp_path.glob(".wtbot-restore-*"))


def test_restore_cleans_up_after_database_constraint_failure(tmp_path: Path) -> None:
    original, archive, rebuilt = (
        tmp_path / name for name in ("source.db", "dump.json", "rebuilt.db")
    )
    make_database(original)
    dump = write_dump(original, archive)
    for table in dump.tables:
        if table.name == "site":
            for row in table.rows:
                row.fields["label"] = "duplicate-label"
    archive.write_text(dump.model_dump_json())
    with pytest.raises(sqlite3.IntegrityError):
        restore_dump(archive, rebuilt, ignore_columns=frozenset({"site.legacy_note"}))
    assert not rebuilt.exists()
    assert not list(tmp_path.glob(".wtbot-restore-*"))


def _as_before_meta_was_keyed_to_titles(raw: dict) -> None:
    """Rewrite a current dump's ProofreadPageMeta and annotations into their
    pre-step-2 shape: keyed by ``page_pk``, referencing pages."""
    for table in raw["tables"]:
        if table["name"] == "scanannotation":
            table["key_fields"] = ["page_pk", "annotation_id"]
            for row in table["rows"]:
                row["key"][0]["table"] = "page"
                refs = row["references"]
                refs["page_pk"] = {**refs.pop("title_pk"), "table": "page"}
            continue
        if table["name"] != "proofreadpagemeta":
            continue
        table["key_fields"] = ["page_pk"]
        for row in table["rows"]:
            row["key"][0]["table"] = "page"
            refs = row["references"]
            refs["page_pk"] = {**refs.pop("title_pk"), "table": "page"}
            refs["index_page_pk"] = {**refs.pop("index_title_pk"), "table": "page"}


def _as_before_works_shared_their_pairings_key(raw: dict) -> None:
    """Rewrite a current dump's IndexLink/PageLink into their earlier shape:
    the work keyed by its own ``page_link_pk`` reference, and every pairing
    carrying an ``index_link_pk`` (null here: the only pairing is the work's
    own, which never pointed at itself in practice)."""
    for table in raw["tables"]:
        if table["name"] == "indexlink":
            table["key_fields"] = ["page_link_pk"]
            for row in table["rows"]:
                row["references"]["page_link_pk"] = row["references"].pop("pk")
        if table["name"] == "pagelink":
            for row in table["rows"]:
                row["references"]["index_link_pk"] = None


def _every_reference_names_a_page(value):
    """Before titles existed, every reference that now names a title named a
    page -- including those nested inside other tables' keys (a work's key is
    its pairing's, which is two pages)."""
    if isinstance(value, dict):
        if value.get("table") == "title":
            value = {**value, "table": "page"}
        return {k: _every_reference_names_a_page(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_every_reference_names_a_page(v) for v in value]
    return value


def test_a_dump_taken_before_titles_existed_restores_with_them(tmp_path: Path) -> None:
    """The backup taken before a schema change is older than the code restoring
    it. A pre-Title dump has no title table, no page->title reference, and the
    old ProofreadPageMeta column names; the restore upgrades it step by step,
    with the same rules the in-place migrations use."""
    original, archive, legacy, rebuilt = (
        tmp_path / name
        for name in ("source.db", "dump.json", "legacy.json", "rebuilt.db")
    )
    make_database(original, offset=100)
    write_dump(original, archive)

    models = {"Index:Book": "proofread-index", "Page:Book/1": "proofread-page"}
    raw = json.loads(archive.read_text())
    # Before titles, the address's own columns were the page's, and so was
    # fetch_error (never written, since dropped).
    address = {
        json.dumps(row["key"]): {
            field: row["fields"].pop(field)
            for field in ("namespace_key", "fetch_status", "dirty")
        }
        for table in raw["tables"]
        if table["name"] == "title"
        for row in table["rows"]
    }
    raw["tables"] = [t for t in raw["tables"] if t["name"] != "title"]
    for table in raw["tables"]:
        if table["name"] == "page":
            for row in table["rows"]:
                row["fields"] |= address[json.dumps(row["key"])]
                row["fields"]["fetch_error"] = None
                row["references"].pop("pk")
                on_source = row["key"][0]["key"] == ["source", "en"]
                row["fields"]["content_model"] = (
                    models.get(row["fields"]["title"]) if on_source else None
                )
    _as_before_meta_was_keyed_to_titles(raw)
    _as_before_works_shared_their_pairings_key(raw)
    for table in raw["tables"]:
        if table["name"] == "indexmeta":
            table["key_fields"] = ["page_pk"]
            for row in table["rows"]:
                row["references"]["page_pk"] = row["references"].pop("title_pk")
    raw["tables"] = _every_reference_names_a_page(raw["tables"])
    legacy.write_text(json.dumps(raw))

    restore_dump(legacy, rebuilt, ignore_columns=frozenset({"site.legacy_note"}))
    with sqlite3.connect(rebuilt) as connection:
        # The work came back sharing its pairing's key, the pairing's sides
        # are titles, and the index metadata is keyed to the index's title.
        assert connection.execute(
            "SELECT count(*) FROM indexlink w JOIN pagelink p ON p.pk = w.pk"
            " JOIN title a ON a.pk = p.local_page_pk"
            " JOIN title b ON b.pk = p.remote_page_pk"
        ).fetchone() == (1,)
        assert connection.execute(
            "SELECT t.title, m.short_name, m.page_count FROM indexmeta m"
            " JOIN title t ON t.pk = m.title_pk"
        ).fetchall() == [("Index:Book", "Book", 9)]
        assert connection.execute(
            "SELECT title, namespace_key, fetch_status, dirty FROM title"
            " WHERE namespace_key IS NOT NULL"
        ).fetchall() == [("Page:Book/1", 250, "done", 1)]
        titles = connection.execute("""
            SELECT s.family, t.title, t.expected_content_model, t.pk = p.pk
            FROM title t JOIN page p ON p.pk = t.pk JOIN site s ON s.pk = t.site_pk
            ORDER BY s.family, t.title
            """).fetchall()
        meta = connection.execute("""
            SELECT page.title, idx.title FROM proofreadpagemeta meta
            JOIN title page ON page.pk = meta.title_pk
            JOIN title idx ON idx.pk = meta.index_title_pk
            """).fetchall()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert titles == [
        ("source", "Index:Book", "proofread-index", 1),
        ("source", "Page:Book/1", "proofread-page", 1),
        # No model on record: MediaWiki's own fallback, as in the migration.
        ("target", "Index:Book", "wikitext", 1),
    ]
    assert meta == [("Page:Book/1", "Index:Book")]


def test_a_dump_taken_before_meta_was_keyed_to_titles_restores(
    tmp_path: Path,
) -> None:
    """Between steps 1 and 2 of the Title split, ProofreadPageMeta still named
    its columns page_pk / index_page_pk and referenced pages. A backup from
    then carries those names in its references *and* in its natural key; the
    restore renames both and retargets them at the title with the same key."""
    original, archive, legacy, rebuilt = (
        tmp_path / name
        for name in ("source.db", "dump.json", "legacy.json", "rebuilt.db")
    )
    make_database(original, offset=100)
    write_dump(original, archive)

    raw = json.loads(archive.read_text())
    _as_before_meta_was_keyed_to_titles(raw)
    legacy.write_text(json.dumps(raw))

    restore_dump(legacy, rebuilt, ignore_columns=frozenset({"site.legacy_note"}))
    with sqlite3.connect(rebuilt) as connection:
        assert connection.execute("""
            SELECT page.title, idx.title, meta.page_number
            FROM proofreadpagemeta meta
            JOIN title page ON page.pk = meta.title_pk
            JOIN title idx ON idx.pk = meta.index_title_pk
            """).fetchall() == [("Page:Book/1", "Index:Book", 1)]
        assert connection.execute("""
            SELECT t.title, a.annotation_id FROM scanannotation a
            JOIN title t ON t.pk = a.title_pk
            """).fetchall() == [("Page:Book/1", "box-1")]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_a_dump_with_since_dropped_tables_restores_without_them(tmp_path: Path) -> None:
    """Transclusion and FileMeta were dropped for redesign. A dump that still
    carries them is not refused as having unexpected tables; they are left out."""
    original, archive, legacy, rebuilt = (
        tmp_path / name
        for name in ("source.db", "dump.json", "legacy.json", "rebuilt.db")
    )
    make_database(original)
    write_dump(original, archive)
    raw = json.loads(archive.read_text())
    raw["tables"] += [
        {"name": "transclusion", "key_fields": [], "rows": []},
        {"name": "filemeta", "key_fields": ["page_pk"], "rows": []},
    ]
    legacy.write_text(json.dumps(raw))

    restore_dump(legacy, rebuilt, ignore_columns=frozenset({"site.legacy_note"}))
    with sqlite3.connect(rebuilt) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert not {"transclusion", "filemeta"} & tables
