# Backlog — small, unowned, unscheduled

Items too small to own a document, and residue left behind by work that is
otherwise finished. Nothing here blocks anything; it is here so it stays
findable instead of living as a footnote in a completed plan.

Anything that grows past a couple of lines should become its own file under
`todo/` (if it is work) or `design/` (if it is a shape to decide on first).

## Backend switching (from `docs/done/wtbot-base-url-switching.md`)

- [ ] **Preview panes do not follow a backend switch.** They keep their
      last-rendered HTML until the next render; they do not subscribe to
      `WtVfsService.BACKEND_SWITCHED`. Everything else — the VFS cache, open
      editors, the tool window, `OcrCatalogService` — is rebound by
      `WtBackendSwitcher`.
- [ ] **No migration from the old project-level setting.** Non-default values
      in `.idea/wikitext-vfs.xml` are dropped rather than carried into the new
      application-level `WtbotAppSettings`. Decide whether that is worth a
      one-shot import or should simply be documented as a breaking change.

## Logging (from `docs/reference/logging.md` §5)

- [ ] uvicorn's access log and the `wtbot.api.errors` lines are separate
      loggers with separate formats. A single access-log middleware could unify
      them and stamp the request id on successful requests too.
- [ ] The reserved 1856x ports (local mediawiki pair, OCR) are unassigned until
      those services actually move into the dev-machine layout.

## Locator index (from `docs/reference/locator-index-design.md`)

- [ ] **Verify the one inferential `<pagelist>` rule against a real rendered
      Index** — that a `blank`/`text` entry does not shift the running page
      count. It matches every example built against so far and matches physical
      intuition, but it is an inference, not a readback. Compare a handful of
      `compute_labels` outputs against the printed numbers visible in the page
      images.
- [ ] **Populate the `Transclusion` table** by scanning mainspace for
      `<pages index=".." from=".." to=".." />`. The table exists in the schema
      and nothing writes it, which is why locator lookups resolve only to the
      `Page:` side and cannot yet build a `{{double link}}`'s mainspace
      argument.
- [ ] **Surface sections with a `begin` but no companion `{{anchor}}`** — a
      real gap (the `{{double link}}` would point at a fragment that does not
      exist). The data to detect it is already collected; nothing checks.
- [ ] **Plugin-side consumption**: `VfsBackend.lookupPageNumbers` /
      `.lookupSections` plus a `FakeVfsBackend` implementation, and a
      completion contributor inside `{{double link|...}}`, behind a
      `wikitext.editing.*` registry key like the rest of the editing features.

## Speculative designs, deliberately not scheduled

These are in `design/` rather than `todo/` because the decision precedes the
work. Listed here only so the backlog is a complete index of what is pending:

- `docs/design/scan-image-modeling.md` — reference scans as first-class
  objects (source / rendition / choice). Nothing implemented, nothing proposed
  for now. It does name one *live* bug worth fixing on its own merits: the scan
  bytes cache keys on `{page_pk}-{width}`, so a re-uploaded scan is served
  stale forever.
- `docs/design/templatedata-future.md` — TemplateData-driven completion, hover
  docs and inspections. Not scheduled; the point of the document is which seams
  to keep clean now.
</content>
