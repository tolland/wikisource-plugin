"""Restore a natural-key dump into a new database using the current models.

Run with ``python -m wtbot.maintenance.restore DUMP OUTPUT_DATABASE``.
"""

import argparse
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlmodel import SQLModel, create_engine

from wtbot.db import stamp_db
from wtbot.maintenance.dump import (
    NATURAL_KEYS,
    OMITTED_TABLES,
    DatabaseDump,
    Record,
    Reference,
    Scalar,
    TableDump,
    _quote,
    _relationships,
)


@dataclass(frozen=True)
class PreparedTable:
    name: str
    columns: tuple[str, ...]
    rows: list[tuple[Scalar, ...]]


@dataclass(frozen=True)
class RestoreResult:
    tables: int
    rows: int
    ignored_columns: tuple[str, ...]
    external_files: int


def _identity(table: str, row: Record) -> str:
    return Reference(table=table, key=row.key).model_dump_json()


def _add_titles_to_legacy_dump(dump: DatabaseDump) -> DatabaseDump:
    """Give a dump taken before Title existed the titles its pages imply.

    A dump is the backup taken *before* a schema change, so it is normally
    older than the code restoring it. Before the Title table, every page was
    its own address; now every page shares its pk with a Title at the same
    (site, title). So each page row yields one title row with the same natural
    key, and the page gains the ``pk`` reference that states the sharing.

    The expected content model is the page's own where it had one, else
    MediaWiki's ``wikitext`` -- the same rule the migration applies in place,
    so an old database reaches the same state whichever route it takes.
    """
    if any(table.name == "title" for table in dump.tables):
        return dump
    pages = next((table for table in dump.tables if table.name == "page"), None)
    if pages is None:
        return dump  # let _prepare report the missing tables
    titles = []
    upgraded_pages = []
    for row in pages.rows:
        title_ref = Reference(table="title", key=row.key)
        titles.append(
            Record(
                key=row.key,
                fields={
                    "title": row.fields.get("title"),
                    "expected_content_model": row.fields.get("content_model")
                    or "wikitext",
                },
                references={"site_pk": row.references.get("site_pk")},
            )
        )
        upgraded_pages.append(
            row.model_copy(update={"references": {**row.references, "pk": title_ref}})
        )
    tables = [
        (
            table.model_copy(update={"rows": upgraded_pages})
            if table.name == "page"
            else table
        )
        for table in dump.tables
    ]
    tables.append(
        TableDump(name="title", key_fields=NATURAL_KEYS["title"], rows=titles)
    )
    return dump.model_copy(update={"tables": tables})


# Columns that later schema steps renamed, and the table their reference now
# targets. A Page and its Title share a natural key (site, title), so a
# reference to a page's key is equally a reference to its title's key; only the
# target table name changes.
_RENAMED_REFERENCES: dict[tuple[str, str], tuple[str, str]] = {
    ("proofreadpagemeta", "page_pk"): ("title_pk", "title"),
    ("proofreadpagemeta", "index_page_pk"): ("index_title_pk", "title"),
    # A work used to point at its pairing; now it shares the pairing's key.
    ("indexlink", "page_link_pk"): ("pk", "pagelink"),
    # Annotations are drawn on a title's scan, whether or not it is saved yet.
    ("scanannotation", "page_pk"): ("title_pk", "title"),
    ("boxrangelink", "page_pk"): ("title_pk", "title"),
    ("texttargetanchor", "page_pk"): ("title_pk", "title"),
}

# References that later steps dropped because they were derivable. A work's
# page pairs are now derived from each page's index, so the pointer goes.
_DROPPED_REFERENCES: frozenset[tuple[str, str]] = frozenset(
    {("pagelink", "index_link_pk")}
)


def _rename_legacy_references(dump: DatabaseDump) -> DatabaseDump:
    """Carry references across columns renamed since the dump was taken.

    Step 2 of the Title/WikiPage split keyed ProofreadPageMeta to its Title:
    ``page_pk`` became ``title_pk`` and ``index_page_pk`` ``index_title_pk``.
    A dump from before that names the old columns, both in its references and
    in the natural key built from them. Renaming is safe because the values
    are the same row: step 1 gave every page a title at the same address.

    IndexLink's ``page_link_pk`` became its ``pk`` the same way: the work now
    shares its pairing's key, and the reference it held already named that
    pairing, so only the column name changes.
    """

    def retarget(ref: Reference | None, target: str) -> Reference | None:
        return None if ref is None else ref.model_copy(update={"table": target})

    tables = []
    for table in dump.tables:
        renames = {
            old: new
            for (name, old), new in _RENAMED_REFERENCES.items()
            if name == table.name
        }
        if not any(field in renames for field in table.key_fields) and not any(
            column in renames for row in table.rows for column in row.references
        ):
            tables.append(table)
            continue
        key_fields = tuple(renames.get(f, (f, None))[0] for f in table.key_fields)
        rows = []
        for row in table.rows:
            references = {
                renames[column][0] if column in renames else column: (
                    retarget(ref, renames[column][1]) if column in renames else ref
                )
                for column, ref in row.references.items()
            }
            key = tuple(
                (
                    retarget(value, renames[field][1])
                    if field in renames and isinstance(value, Reference)
                    else value
                )
                for field, value in zip(table.key_fields, row.key, strict=True)
            )
            rows.append(row.model_copy(update={"key": key, "references": references}))
        tables.append(table.model_copy(update={"key_fields": key_fields, "rows": rows}))
    return dump.model_copy(update={"tables": tables})


def _drop_legacy_references(dump: DatabaseDump) -> DatabaseDump:
    """Discard references to columns that later steps derived instead."""
    tables = []
    for table in dump.tables:
        dropped = {column for name, column in _DROPPED_REFERENCES if name == table.name}
        if not dropped:
            tables.append(table)
            continue
        rows = [
            row.model_copy(
                update={
                    "references": {
                        column: ref
                        for column, ref in row.references.items()
                        if column not in dropped
                    }
                }
            )
            for row in table.rows
        ]
        tables.append(table.model_copy(update={"rows": rows}))
    return dump.model_copy(update={"tables": tables})


# Applied in order: each brings a dump from one schema step to the next, and
# does nothing to a dump that is already past it.
_LEGACY_UPGRADES = (
    _add_titles_to_legacy_dump,
    _rename_legacy_references,
    _drop_legacy_references,
)


def _shares_primary_key(table_name: str) -> bool:
    """Whether this table's ``pk`` is also a foreign key into another table.

    Such a row has no identity of its own to allocate: it *is* the row it
    references (every Page is a Title), so it takes that row's number, and
    everything referencing it resolves to the same number.
    """
    return "pk" in _relationships(table_name)


def _prepare(dump: DatabaseDump, ignore_columns: frozenset[str]) -> list[PreparedTable]:
    for upgrade in _LEGACY_UPGRADES:
        dump = upgrade(dump)
    names = [table.name for table in dump.tables]
    if len(set(names)) != len(names) or set(names) != set(NATURAL_KEYS):
        raise ValueError("Dump must contain exactly the selected natural-key tables")
    if set(dump.omitted_tables) != set(OMITTED_TABLES):
        raise ValueError("Unexpected omitted tables")
    for qualified in ignore_columns:
        name, separator, column = qualified.partition(".")
        if not separator or name not in NATURAL_KEYS:
            raise ValueError(f"Invalid ignored column: {qualified}")
        if column in SQLModel.metadata.tables[name].columns:
            raise ValueError(f"Cannot ignore current model column: {qualified}")

    # Allocate all surrogate identities before inserting anything. This allows
    # forward and cyclic references without inserting temporary null values.
    allocated: dict[str, int] = {}
    identities: set[str] = set()
    for table in dump.tables:
        if table.key_fields != NATURAL_KEYS[table.name]:
            raise ValueError(f"Unexpected natural-key fields in {table.name}")
        for number, row in enumerate(table.rows, start=1):
            identity = _identity(table.name, row)
            if identity in identities:
                raise ValueError(f"Duplicate natural key in {table.name}")
            identities.add(identity)
            if "pk" in SQLModel.metadata.tables[
                table.name
            ].columns and not _shares_primary_key(table.name):
                allocated[identity] = number
    # Second pass, now every independent identity has its number: a row whose
    # pk is a reference takes the number of the row it refers to.
    for table in dump.tables:
        if not _shares_primary_key(table.name):
            continue
        for row in table.rows:
            ref = row.references.get("pk")
            target = ref.model_dump_json() if ref is not None else None
            if target not in allocated:
                raise ValueError(f"Unresolved shared primary key in {table.name}")
            allocated[_identity(table.name, row)] = allocated[target]

    prepared = []
    for table in dump.tables:
        model = SQLModel.metadata.tables[table.name]
        relationships = _relationships(table.name)
        columns = tuple(column.name for column in model.columns)
        rows = []
        for row in table.rows:
            if set(row.references) != set(relationships):
                raise ValueError(f"Unexpected relationship columns in {table.name}")
            if set(row.fields) & (set(relationships) | {"pk"}):
                raise ValueError(f"Raw primary/foreign keys in {table.name}")
            # Do not trust a key inconsistent with its own data: that would
            # silently attach other rows to the wrong identity on restoration.
            actual_key = tuple(
                (
                    row.references[field]
                    if field in relationships
                    else row.fields.get(field)
                )
                for field in table.key_fields
            )
            if actual_key != row.key:
                raise ValueError(f"Natural key disagrees with row data in {table.name}")
            values = {}
            for column, value in row.fields.items():
                if column not in model.columns:
                    if f"{table.name}.{column}" not in ignore_columns:
                        raise ValueError(
                            f"Unknown legacy column: {table.name}.{column}; explicitly ignore it to discard"
                        )
                else:
                    values[column] = value
            if "pk" in model.columns:
                values["pk"] = allocated[_identity(table.name, row)]
            for column, ref in row.references.items():
                if ref is None:
                    values[column] = None
                    continue
                if ref.table != relationships[column]:
                    raise ValueError(
                        f"Wrong reference target for {table.name}.{column}"
                    )
                identity = ref.model_dump_json()
                if identity not in allocated:
                    raise ValueError(f"Unresolved reference for {table.name}.{column}")
                values[column] = allocated[identity]
            if set(values) != set(columns):
                missing = sorted(set(columns) - set(values))
                raise ValueError(
                    f"Missing columns in {table.name}: {', '.join(missing)}"
                )
            rows.append(tuple(values[column] for column in columns))
        prepared.append(PreparedTable(table.name, columns, rows))
    return prepared


def restore_dump(
    source: Path,
    output: Path,
    *,
    ignore_columns: frozenset[str] = frozenset(),
) -> RestoreResult:
    """Publish a complete new database, or leave the destination untouched."""
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    dump = DatabaseDump.model_validate_json(source.read_bytes())
    prepared = _prepare(dump, ignore_columns)
    # Build beside the destination, so a no-clobber hard link can publish the
    # finished file atomically on the same filesystem. Failures leave no output.
    with TemporaryDirectory(prefix=".wtbot-restore-", dir=output.parent) as directory:
        temporary = Path(directory) / "database.db"
        temporary.touch(mode=0o600)
        engine = create_engine(f"sqlite:///{temporary}")
        try:
            SQLModel.metadata.create_all(engine)
            with closing(sqlite3.connect(temporary)) as connection, connection:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("BEGIN")
                connection.execute("PRAGMA defer_foreign_keys=ON")
                for table in prepared:
                    columns = ", ".join(map(_quote, table.columns))
                    placeholders = ", ".join("?" for _ in table.columns)
                    connection.executemany(
                        f"INSERT INTO {_quote(table.name)} ({columns}) VALUES ({placeholders})",
                        table.rows,
                    )
                if (
                    connection.execute("PRAGMA foreign_key_check").fetchone()
                    is not None
                ):
                    raise ValueError("Restored database failed foreign-key validation")
                if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise ValueError(
                        "Restored database failed SQLite integrity validation"
                    )
                connection.commit()
            # The schema came from today's models, not the old database's DDL.
            # Record today's migration head so normal startup won't replay it.
            stamp_db(engine)
        finally:
            engine.dispose()
        os.link(temporary, output)
    return RestoreResult(
        tables=len(prepared),
        rows=sum(len(table.rows) for table in prepared),
        ignored_columns=tuple(sorted(ignore_columns)),
        external_files=len(dump.external_files),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--ignore-column",
        action="append",
        default=[],
        metavar="TABLE.COLUMN",
        help="Explicitly discard a legacy column absent from current models",
    )
    args = parser.parse_args()
    result = restore_dump(
        args.dump, args.output, ignore_columns=frozenset(args.ignore_column)
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "tables": result.tables,
                "rows": result.rows,
                "ignored_columns": result.ignored_columns,
                "external_files": result.external_files,
            }
        )
    )


if __name__ == "__main__":
    main()
