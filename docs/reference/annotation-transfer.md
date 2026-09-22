# Annotation dump and load

## Why annotations are special

The SQLite cache is disposable by design. Sites, pages, revisions, content
blobs and the fetch queue are all re-derivable: point wtbot at the wiki (or a
mirror) and fetch again. The local edit journal is the mild exception — a
rebuild loses the per-save history — but nothing the wiki does not already
hold is lost with it.

Annotations are the one thing that only exists here:

- `ScanAnnotation` — bounding boxes drawn over a page's scan, in normalized
  full-page coordinates;
- `TextTargetAnchor` — the transcription ranges those boxes' content is
  destined for;
- `BoxRangeLink` — which box feeds which range.

Nobody drew them upstream, so nothing upstream can give them back. That single
asymmetry is what turned an otherwise throwaway database into something a
schema migration has to be careful with. `wtbot annotations dump` / `load`
removes the asymmetry: the annotation tables become a file, and the database
goes back to being disposable.

## The file

Written by `wtbot annotations dump`, defined in `wtbot/annotation_transfer.py`
(`AnnotationDump`), a versioned JSON document grouped by page:

```json
{
  "version": 1,
  "created_at": "2026-09-22T15:09:37.128941Z",
  "pages": [
    {
      "site_label": "local",
      "site_family": "wikisource",
      "site_code": "en",
      "title": "Page:X.djvu/3",
      "source_page_pk": 1,
      "boxes":   [{"annotation_id": "b1", "x": 0.1, "y": 0.1, "width": 0.5,
                   "height": 0.2, "label": "hi", "category": null}],
      "anchors": [{"annotation_id": "r1", "text_start": 0, "text_end": 9,
                   "anchor_revid": 5}],
      "links":   [{"box_annotation_id": "b1", "range_annotation_id": "r1"}]
    }
  ]
}
```

The addressing is the point. Rows are keyed in the database by `page_pk`, and
a page pk is local to one database — rebuild the cache and every one of them
changes. So the dump joins against `Page` and `Site` and carries
**(site label, page title)**, which survives the rebuild. `source_page_pk` is
provenance only; load ignores it. Within a page, the client-generated
`annotation_id` stays the join key between boxes, anchors and links, exactly
as in the database.

`anchor_revid` travels with each anchor: an anchor is only trustworthy against
the revision it was measured on, and dropping the revid would silently turn a
stale anchor into a fresh-looking one.

Pages with no annotation records of any kind are left out.

## Commands

```bash
uv run wtbot annotations dump -o annotations.json            # everything
uv run wtbot annotations dump -o - --label local             # one site, to stdout
uv run wtbot annotations dump -o ann.json --title "Page:X.djvu/3"

uv run wtbot annotations load -i annotations.json            # keep existing rows
uv run wtbot annotations load -i annotations.json --replace  # overwrite them
uv run wtbot annotations load -i annotations.json --label staging  # relabelled site
uv run wtbot annotations load -i annotations.json --dry-run
```

Both take `--database-url`, defaulting to `WTBOT_DATABASE_URL` and then to
`sqlite:///database.db`.

`dump` deliberately does **not** run migrations: a dump is most useful taken
*before* a migration, and migrating the database you are trying to preserve is
the opposite of what was asked for. Against a database with no wtbot tables it
says so and exits 1 rather than raising a traceback.

`load` is conservative:

- nothing is created implicitly — a record whose site label or page title is
  absent from the target database is reported and skipped, never conjured into
  a `Site` or a placeholder `Page`;
- existing rows are kept unless `--replace`, so a load is safe to re-run and
  safe to point at a database that has moved on;
- links are written last, and one whose box or range did not make it across is
  reported rather than written as a dangling row.

`--label` re-homes a whole dump onto a differently-labelled site — the usual
case being a dump taken from `staging` and loaded into `local`.

## `annotations import-svg`

The same command group also holds the one-shot import of the pre-SQL storage
(`blob_root/annotations/{page_pk}.svg`), which used to be a top-level command.
It is unrelated to the dump format above and exists only to rescue boxes drawn
before `ScanAnnotation` existed.
