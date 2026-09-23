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


def _prepare(dump: DatabaseDump, ignore_columns: frozenset[str]) -> list[PreparedTable]:
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
            if "pk" in SQLModel.metadata.tables[table.name].columns:
                allocated[identity] = number

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
