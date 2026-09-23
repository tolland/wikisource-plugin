# Natural-key database dump

Run from the repository root, without starting the API or applying migrations:

```bash
mkdir -p backups
uv run python -m wtbot.maintenance.dump database.db backups/database-natural-keys.json
```

The source is opened read-only inside a SQLite read transaction. An existing
output is never overwritten. The JSON file is created with mode 0600 because
site credentials and OCR API tokens are included. `backups/` is ignored by Git.

The export includes the 19 tables in `NATURAL_KEYS`, excluding `editjournal`,
`fetchrequest`, `commit`, `promotion`, and `promotionbatch`. It does not export
schema DDL, Alembic temporary tables, or migration bookkeeping as application
data. The original Alembic revision is recorded for provenance only.

Site identity comes from `Site.natural_key_fields`, declared through
`NaturalKeyMixin`. Other table identities are explicitly listed in `NATURAL_KEYS`.
For example, a Page key combines a Site reference `(family, code)` with its title;
a Revision key combines a Page reference with its wiki-local revid. Page and
revision link keys retain local/remote orientation. FileBlob uses page, SHA-1,
and upload timestamp. Transclusion uses site, source page, index title, and range.
The exporter rejects duplicate keys, including nullable-key collisions, rather
than merging or dropping records.

Each table contains `key_fields` and `rows`. Each row contains:

- `key`: natural-key values in declared order, recursively expanded references.
- `fields`: scalar data, including any legacy columns, without surrogate `pk`.
- `references`: source column names mapped to `{table, key}` objects or null.

Relationships come from current model metadata, so missing or unnamed database
constraints do not affect the export. `page.latest_revision_pk` is explicitly
included despite not being a declared foreign key. Annotation ID strings remain
unchanged and, together with their natural-key Page reference, retain box/anchor
relationships. Missing relationship targets abort export before output creation.

## Restore into a new database

```bash
uv run python -m wtbot.maintenance.restore backups/database-natural-keys.json backups/database-rebuilt.db
```

The destination must not exist. The importer creates all tables and named
constraints from the current SQLModel metadata, and stamps the result at the
current Alembic head. The five omitted tables exist but remain empty. This is a
fresh rebuild, not an in-place migration or a merge into an existing database.

New primary keys are allocated up front, and `(table, key)` references are
resolved to those IDs. Foreign-key checks are deferred until the import
transaction commits, allowing Page/Revision and IndexLink/PageLink cycles.
The importer checks foreign keys and SQLite integrity before publishing the
completed database atomically. Failures leave no destination database; existing
files are never replaced. The result has owner-only permissions (0600).

Unexpected tables, duplicate or inconsistent identities, unresolved references,
and missing model columns fail validation. Legacy columns absent from today's
models also fail unless explicitly discarded with a repeatable option:

```bash
uv run python -m wtbot.maintenance.restore dump.json rebuilt.db --ignore-column site.legacy_note
```

Column names in this option must be absent from the current model. No current
model fields can be discarded. Retain the original dump if discarding legacy
data. The importer does not replace the running application's database;
switching to the rebuilt file is a separate operation.

`external_files` lists paths from FileBlob and proofread-page metadata. The binary
files themselves are not included; retain the blob/image directories alongside
the dump. Embedded paths are preserved, not rewritten for a new location.
