# Text-editing features: implementation plan

Scope: Surround With, formatting toggle actions with shortcuts, Generate table,
and subtree search & replace — for plain `.wt`/`.wiki` files and for
`wikisource://` files backed by the wtbot VFS.

A key structural observation up front: features 1–3 operate purely on the
`Editor`/`Document`/PSI layer. `WtVirtualFile` is writable and routes saves
through `getOutputStream` → `VfsBackend.writeContent` → EditJournal, so
anything that edits an open Document works identically for plain files and VFS
files with **zero** VFS-specific code. Only feature 4 (search/replace across a
subtree, including pages that are not open) needs new contract surface on
`VfsBackend` and the sidecar.

## Shared infrastructure

### `WtWrapTags` — one catalog of wrappable constructs (wikitext-core)

A single enum/registry describing each wrappable construct, consumed by the
surrounders, the toggle actions, and (later) intentions:

```kotlin
enum class WtWrapTag(
    val tagName: String?,        // null for quote-style markers
    val prefix: String,          // "<code>", "'''", "<section begin=\"$NAME$\" />"
    val suffix: String,
    val block: Boolean,          // put markers on their own lines
    val needsName: Boolean,      // section: template variable to fill
)
```

Entries: `CODE`, `MATH`, `NOWIKI`, `PRE`, `NOINCLUDE`, `INCLUDEONLY`, `REF`,
`POEM`, `BOLD` (`'''`), `ITALIC` (`''`), `SECTION` (paired
`<section begin=…/>` / `<section end=…/>`). The verbatim-tag list already in
`WikitextLexer.flex` (`nowiki`, `pre`, `math`, …) should be cross-checked so
the catalog and lexer agree on which tags swallow their content.

New code lives in a new package `org.limepepper.lang.wikitext.editing`
(actions/UI in `wikitext-ui`; pure text/markup helpers in `wikitext-core` so
they are unit-testable without the IDE fixture).

## 1. Surround With (Ctrl+Alt+T)

Platform pieces (mirroring `GroovySurroundDescriptor` / the Markdown plugin):

- **`WtSurroundDescriptor : SurroundDescriptor`** — registered via
  `<lang.surroundDescriptor language="Wikitext" .../>` in
  `wikisource.wikitext-ui.xml`. Wikitext selections are free-form prose rather
  than statement lists, so `getElementsToSurround(file, start, end)` should be
  permissive: return the PSI elements intersecting the range, falling back to
  the containing element/file — an empty array is what disables the action, and
  we almost never want it disabled inside a wikitext file.
- **`WtTagSurrounder(tag: WtWrapTag) : Surrounder`** — one parameterized class
  instantiated per catalog entry; `surroundElements` replaces the selection
  with `prefix + selection + suffix` via the Document (not PSI manipulation —
  wikitext PSI is too loose to be worth building trees by hand) and returns
  the caret `TextRange`.
- **`WtSectionSurrounder`** — the variable-filling case. After inserting
  `<section begin="" />…<section end="" />`, start a live template with
  `TemplateManager`/`TemplateBuilderImpl` containing one `$NAME$` variable and
  a mirror copy in the end tag, so typing the section name fills both
  attributes simultaneously (the same pattern Java's surround templates use).
  This avoids a modal dialog and keeps the interaction in the editor.
- The descriptor's `isExclusive = false` so platform surrounders (live
  templates) still appear in the popup.

VFS impact: none — pure Document edits.

Tests: `LightPlatformCodeInsightTestCase`-style data-driven tests
(`before.wt` + selection markers → `after.wt`) under
`wikitext-ui/src/test/`, one per catalog entry plus the section-template case.

## 2. Formatting toggle actions and shortcuts (Ctrl+B / Ctrl+I style)

- **`WtBaseToggleStyleAction`** — modeled on Markdown's
  `BaseToggleStateAction`: given caret/selection, detect whether it is already
  wrapped in the marker, then remove or add. Detection must be **text-scan
  based** for now: the lexer has no `BOLD`/`ITALIC` tokens (`'''`/`''` are
  currently unstructured text), so a small `WtStyleMarkerScanner` in
  `wikitext-core` finds enclosing markers on the caret's line. Optionally, add
  proper quote tokens to the lexer later and switch detection to tokens; don't
  block the feature on grammar work.
- Subclasses: `WtToggleBoldAction` (`'''`), `WtToggleItalicAction` (`''`),
  `WtToggleCodeAction` (`<code>`), `WtToggleNowikiAction` — all thin wrappers
  over the catalog + scanner.
- **Registration and shortcut conflicts**: register in the `<actions>` block
  with `<keyboard-shortcut first-keystroke="control B" keymap="$default"/>`
  etc. `Ctrl+B` is Go to Declaration and `Ctrl+I` is Implement Methods, so two
  guards are required, exactly as Markdown does it:
  1. `update()` enables the action only when the editor's PSI file language is
     Wikitext (disable everywhere else so the IDE falls through to the
     platform action).
  2. An **`ActionPromoter`** (`WtEditingActionPromoter`, registered as
     `<actionPromoter/>`) that moves our toggle actions to the front of the
     candidate list when the context editor is a wikitext file — this is what
     actually resolves the shared-shortcut ambiguity deterministically.
- Optional follow-up: Markdown-style floating toolbar on selection
  (`floatingToolbarProvider`) offering the same actions; nice but not part of
  the core infrastructure.

VFS impact: none.

## 3. Generate table (Alt+Insert)

- **`WtGenerateTableAction`** added to the Generate popup via
  `<add-to-group group-id="GenerateGroup"/>`, enabled only in wikitext files.
- Phase 1 UI: a small dialog (rows/columns spinners, "header row" checkbox,
  optional `class="wikitable"`). Phase 2 (optional): Markdown's hover
  grid-picker component for NxM selection.
- **`WtTableMarkupBuilder`** in `wikitext-core` — pure function
  `(rows, cols, header, cssClass) -> String` emitting `{| … |}` markup; unit
  tested without any IDE fixture. The action just inserts the string at the
  caret and positions the caret in the first cell.

VFS impact: none.

## 4. Search & replace across a subtree of Pages

The OCR-misreading workflow ("force"/"foree" across all `Page:` children of an
`Index:`). Plain files are already covered by the IDE's Replace in Files over a
directory. The interesting case is `wikisource://`: platform Find-in-Files does
not see a custom VFS (its files are not in the project content roots or
indexes), and pages need to be searchable *without* opening each one.

The content is already sitting in wtbot's SQLite cache, so the search itself
belongs server-side; the replace belongs client-side so every write keeps going
through the one existing write path (Document if open, else
`VfsBackend.writeContent` with `baseRevid` conflict detection → EditJournal).

### Sidecar (wtbot)

- New router `src-py/wtbot/api/search.py`: `POST /vfs/search` with a typed
  request `{root_path, query, is_regex, case_sensitive, whole_words}`.
  `root_path` scopes the search to a subtree (an `Index:` node scopes to its
  `Page:` children — the same parent/child relation the fetch fan-out already
  records). Implementation: SQL scan with Python-side matching is fine at
  wikisource scale (hundreds of pages/book); SQLite FTS5 is an optimization to
  defer.
- Response: per-file match groups `{path, revid, matches: [{line, line_text,
  start, end}]}` — offsets against the *cached revision*, plus the revid so
  the client can detect staleness before applying a replace.
- No server-side replace endpoint. Keeping mutation out of the search API
  means EditJournal/dirty-tracking semantics stay in exactly one place.
- Tests: pytest against `FakeWikiClient`-seeded pages.

### Plugin contract (`wikitext-vfs`)

- `VfsBackend.search(rootPath, query, options): List<SearchFileResult>` +
  implementations in `HttpVfsBackend` and `FakeVfsBackend` (the fake makes the
  UI testable offline).

### Plugin UI (`wikitext-ui`)

- **`WtSubtreeSearchReplaceAction`** on the tool-window tree's context menu
  (`WikisourceTreeStructure` nodes for `Index:`/directory entries): "Find/
  Replace in Subtree…".
- **Results panel** (tab in the existing tool window or a dedicated one):
  search field + replace field + options; results tree grouped by page with
  per-match checkboxes and a before/after preview line — a deliberately small
  subset of the platform's UsageView interaction, built with a plain tree
  rather than fighting to reuse `FindInProjectManager` internals.
- **`WtBatchReplacer`** applies checked matches per file:
  1. If the file has an open modified Document → edit the Document (user saves
     as usual).
  2. Otherwise `readContent` → apply replacements right-to-left → `writeContent`
     with the search result's `revid` as `baseRevid`; a `conflict` result is
     surfaced per-file ("page changed since search — re-run search"), never
     silently retried.
  3. Runs on a background task with progress; per-file success/conflict summary
     at the end.
- Because writes land in EditJournal as dirty local edits (not wiki commits),
  a bad batch replace is reviewable and revertible before any `commit` pushes
  it to the wiki — worth stating in the UI copy.

### Deliberately not doing (for now)

Making the platform's own Find in Path index the VFS (via
`IndexableSetContributor` + custom search scopes) would give native
Find/Replace UI, but forces the indexing framework over lazy remote files and
ties us to indexing internals. Revisit only if the custom panel proves limiting.

## Suggested build order

1. `WtWrapTags` catalog + Surround With (descriptor, tag surrounder, section
   surrounder with template variable) + tests.
2. Toggle actions + `WtStyleMarkerScanner` + `ActionPromoter` + shortcuts.
3. Generate table (builder + dialog action).
4. wtbot `/vfs/search` + `VfsBackend.search` + subtree search/replace UI +
   `WtBatchReplacer`.

Each step ships independently; 1–3 are pure-editor features usable on plain
files and VFS files alike from day one.
