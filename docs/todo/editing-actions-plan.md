# Text-editing features — remaining work

Only the unfinished editor actions. Surround With, the `WtWrapTags` catalog and
the apostrophe-quote lexing shipped; their design and rationale are in
`docs/done/editing-actions-built.md`.

The prototyping stance still applies to everything here: each feature goes
behind a `wikitext.editing.*` registry key, competing interaction styles are
selectable at runtime, markup generation stays in the pure renderer
(`WtWrapRenderer`), and losing implementations get deleted along with their key.

See also `docs/design/templatedata-future.md` for the MediaWiki TemplateData
work these seams should stay compatible with.

## Build order

1. **2b. Toggle actions** + token-based detection + `ActionPromoter` + shortcuts.
2. **3. Generate table** (builder + dialog action).
3. **4. Subtree search & replace**: wtbot `/vfs/search` + `VfsBackend.search` +
   the UI + `WtBatchReplacer`.

Each ships independently; 1–2 are pure-editor features usable on plain files
and VFS files alike from day one. Features 1–3 operate purely on the
`Editor`/`Document`/PSI layer, so they work identically for plain `.wt` files
and `wikisource://` VFS files with **zero** VFS-specific code — `WtVirtualFile`
is writable and routes saves through `getOutputStream` →
`VfsBackend.writeContent` → EditJournal. Only feature 4 needs new contract
surface on `VfsBackend` and the sidecar.

## 2b. Formatting toggle actions and shortcuts (Ctrl+B / Ctrl+I style)

- **`WtBaseToggleStyleAction`** — modeled on Markdown's
  `BaseToggleStateAction`: given caret/selection, detect whether it is already
  wrapped in the marker, then remove or add. Detection can now be
  **token-based** thanks to the shipped quote lexing — walk the highlighting
  lexer or PSI leaves on the caret's line looking for the enclosing
  `TWO_APOS`/`THREE_APOS`/`FIVE_APOS` pair, rather than scanning raw text for
  quote characters and having to re-derive MediaWiki's length rules a second
  time.
- Subclasses: `WtToggleBoldAction` (`'''`), `WtToggleItalicAction` (`''`),
  `WtToggleCodeAction` (`<code>`), `WtToggleNowikiAction` — all thin wrappers
  over `WtWrapTagSets.toggleable` + the detector.
- Toggling a five-run is the interesting case and should be specified before
  it is written: removing bold from `'''''x'''''` has to leave `''x''`, which
  means the toggle edits *run lengths*, not whole markers.
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

## Follow-ups left open by the shipped steps

- Quote lexing in the `TEMPLATE`/`LINK`/`TABLE` states (2a covered `WIKI_TEXT`).
- Bold/italic PSI structure, i.e. the pairing pass that resolves the
  five-run ambiguity and respects the single-line rule.
- Syntax highlighting for the new quote tokens (`WtSyntaxHighlighter` does not
  map them yet, so they currently render as plain text).

## Inline rich rendering of quote markup (idea, not yet built)

Observation: the XML/HTML editor shows an entity as its literal character, and
TeXiFy does the same for LaTeX commands. Both are **folding** — a
`FoldingBuilder` replaces a range with placeholder text — not styling. That
suggests two separate, independently useful features for quote markup, worth
keeping apart because they have different risks:

1. **Style the content** — render text between `'''` markers in an actual bold
   font, markers left visible. This is a `TextAttributes` change only: it does
   not alter the character count, so no offset mapping, no interaction with
   folding, and nothing to go wrong when the user edits mid-run.
   `WtQuoteScanner.styledSpans()` already returns exactly the spans this needs
   (it was written for the toggle actions and returns content ranges, not
   marker ranges), so this is close to just an annotator that sets
   `FontType.BOLD` / `ITALIC`.
2. **Fold the markers** — hide the `'''` themselves so a bolded word looks like
   a bolded word. This is the part that changes what the user sees at an
   offset, and it needs care: folds must open when the caret enters them, or
   editing near a marker becomes guesswork.

Recommended order: (1) first, behind a registry key, since it is cheap and
reversible; (2) only if (1) proves it reads well. Doing (2) without (1) would
hide the markup while leaving the text visually unchanged, which is the worst
of both.

Caveat for both: the scanner is line-scoped, which matches MediaWiki's
single-line rule, so an unclosed run styles to end of line and stops. That is
the correct rendering, but it means a stray apostrophe run can visibly restyle
the rest of a line — arguably a useful signal that the markup is unbalanced.
</content>
