"""Export selected SQLite data without depending on its constraint names.

Run with ``python -m wtbot.maintenance.dump DATABASE OUTPUT``.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from sqlmodel import SQLModel

import wtbot.model  # noqa: F401 - register model relationships
from wtbot.model.wiki.site import Site

type Scalar = str | int | float | None

# Keys containing foreign-key columns are expanded recursively to target keys.
# These describe identity, not the order in which tables should be restored.
NATURAL_KEYS: dict[str, tuple[str, ...]] = {
    "boxrangelink": ("title_pk", "box_annotation_id"),
    "content": ("content_sha1", "content_model"),
    "fileblob": ("page_pk", "file_sha1", "upload_timestamp"),
    "indexlink": ("pk",),  # shared with the pairing it tracks
    "indexmeta": ("page_pk",),
    "namespace": ("site_pk", "key"),
    "ocrbackendconfig": ("scope", "name"),
    "page": ("site_pk", "title"),
    "pagelink": ("local_page_pk", "remote_page_pk"),
    "proofreadpagemeta": ("title_pk",),
    "revision": ("page_pk", "revid"),
    "revisionlink": ("local_revision_pk", "remote_revision_pk"),
    "scanannotation": ("title_pk", "annotation_id"),
    "site": Site.natural_key_fields,
    "sitecredential": ("site_pk",),
    "slot": ("revision_pk", "role"),
    "texttargetanchor": ("title_pk", "annotation_id"),
    "title": ("site_pk", "title"),
}
OMITTED_TABLES = (
    "editjournal",
    "fetchrequest",
    "commit",
    "promotion",
    "promotionbatch",
)


class Reference(BaseModel):
    table: str
    key: tuple[Scalar | Reference, ...]


class Record(BaseModel):
    key: tuple[Scalar | Reference, ...]
    fields: dict[str, Scalar]
    references: dict[str, Reference | None]


class TableDump(BaseModel):
    name: str
    key_fields: tuple[str, ...]
    rows: list[Record]


class DatabaseDump(BaseModel):
    format: Literal["wtbot-natural-keys-v1"] = "wtbot-natural-keys-v1"
    source_revisions: list[str]
    omitted_tables: tuple[str, ...] = OMITTED_TABLES
    external_files: list[str]
    tables: list[TableDump]


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _relationships(table_name: str) -> dict[str, str]:
    table = SQLModel.metadata.tables[table_name]
    relationships = {}
    for foreign_key in table.foreign_keys:
        target = foreign_key.column
        if not target.primary_key or len(target.table.primary_key) != 1:
            raise ValueError(f"Unsupported relationship in {table_name}")
        relationships[foreign_key.parent.name] = target.table.name
    if table_name == "page":
        # Intentionally not a SQL foreign key: Page and Revision form a cycle.
        relationships["latest_revision_pk"] = "revision"
    return relationships


def read_dump(database: Path) -> DatabaseDump:
    """Read one consistent snapshot; never migrate or write to the source."""
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN")
        return _read_snapshot(connection)
    finally:
        connection.close()


def _read_snapshot(connection: sqlite3.Connection) -> DatabaseDump:
    rows: dict[str, list[sqlite3.Row]] = {}
    by_pk: dict[str, dict[Scalar, sqlite3.Row]] = {}
    relationships = {name: _relationships(name) for name in NATURAL_KEYS}
    revisions = [
        row[0] for row in connection.execute("SELECT version_num FROM alembic_version")
    ]
    for name in NATURAL_KEYS:
        table = SQLModel.metadata.tables[name]
        pk_columns = list(table.primary_key.columns)
        order = ", ".join(_quote(column.name) for column in pk_columns)
        rows[name] = list(
            connection.execute(f"SELECT * FROM {_quote(name)} ORDER BY {order}")
        )
        if len(pk_columns) == 1:
            by_pk[name] = {row[pk_columns[0].name]: row for row in rows[name]}

    def reference(target: str, pk: Scalar, visiting: frozenset[str]) -> Reference:
        if target not in by_pk or pk not in by_pk[target]:
            # Do not include row contents: credentials and tokens are exported.
            raise ValueError(f"Unresolved reference to {target}, source key {pk!r}")
        return Reference(
            table=target, key=natural_key(target, by_pk[target][pk], visiting)
        )

    def natural_key(name: str, row: sqlite3.Row, visiting: frozenset[str]) -> tuple:
        if name in visiting:
            raise ValueError(f"Cycle in natural-key definition for {name}")
        visiting = visiting | {name}
        return tuple(
            (
                reference(relationships[name][field], row[field], visiting)
                if field in relationships[name] and row[field] is not None
                else row[field]
            )
            for field in NATURAL_KEYS[name]
        )

    tables = []
    external_files: set[str] = set()
    for name, table_rows in rows.items():
        records = []
        seen: set[str] = set()
        for row in table_rows:
            key = natural_key(name, row, frozenset())
            identity = Reference(table=name, key=key).model_dump_json()
            if identity in seen:
                raise ValueError(f"Duplicate natural key in {name}; no rows exported")
            seen.add(identity)
            refs = {
                column: (
                    reference(target, row[column], frozenset())
                    if row[column] is not None
                    else None
                )
                for column, target in relationships[name].items()
            }
            # Preserve legacy scalar columns too. Surrogate PKs have no meaning
            # in the rebuilt database; composite/FK keys live in references.
            fields = {
                column: row[column]
                for column in row.keys()
                if column != "pk" and column not in refs
            }
            records.append(Record(key=key, fields=fields, references=refs))
            for column in ("local_path", "raster_path", "thumb_path"):
                if column in fields and fields[column]:
                    external_files.add(str(fields[column]))
        tables.append(TableDump(name=name, key_fields=NATURAL_KEYS[name], rows=records))
    return DatabaseDump(
        source_revisions=revisions, external_files=sorted(external_files), tables=tables
    )


def write_dump(database: Path, output: Path) -> DatabaseDump:
    dump = read_dump(database)
    # O_EXCL prevents overwriting either an earlier dump or the source database.
    # Site passwords and OCR tokens are needed for recreation: owner-only file.
    payload = dump.model_dump_json(indent=2)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(payload)
        stream.write("\n")
    return dump


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    dump = write_dump(args.database, args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows": {table.name: len(table.rows) for table in dump.tables},
                "external_files": len(dump.external_files),
            }
        )
    )


if __name__ == "__main__":
    main()
