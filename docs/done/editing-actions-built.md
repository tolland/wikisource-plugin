# Text-editing features — what shipped

Completed sections of the text-editing plan. The unfinished editor actions are
in `docs/todo/editing-actions-plan.md`; the TemplateData work these seams should
stay compatible with is in `docs/design/templatedata-future.md`.

## Prototyping stance (still in force)

This was a kitchen-sink exploration, not a settled design. The platform offers
several interaction styles for each feature — in-editor popups, live templates,
modal dialogs, floating toolbars — and which of them are actually pleasant to
use is not knowable in advance. So the rule for everything shipped here:

- **Every feature has an on/off switch, and every competing interaction style
  is selectable at runtime.** These are `Registry` keys (`<registryKey>` in
  `wikisource.wikitext-ui.xml`, read through `WtEditingFlags`), not Settings
  pages — a Settings checkbox is a promise that an option is supported, and
  none of this has earned that yet.
- **Competing implementations share their markup layer.** The pure renderer
  (`WtWrapRenderer`) is the only thing that decides what text gets produced, so
  swapping strategies changes the *interaction* and provably nothing else.
- **Losing implementations get deleted, along with their registry key.** The
  switches are scaffolding, not a permanent configuration surface.

## Shared infrastructure — `WtWrapTags` (wikitext-core)

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
`<section begin=…/>` / `<section end=…/>`). The verbatim-tag list in
`WikitextLexer.flex` (`nowiki`, `pre`, `math`, …) is cross-checked against the
catalog so the two agree on which tags swallow their content.

New code lives in `org.limepepper.lang.wikitext.editing` (actions/UI in
`wikitext-ui`; pure text/markup helpers in `wikitext-core` so they are
unit-testable without the IDE fixture).

## 1. Surround With (Ctrl+Alt+T) — implemented

Shipped shape (differs slightly from the sketch below, which is kept for the
rationale):

| Class | Module | Role |
|-------|--------|------|
| `WtWrapTag` / `WtWrapTagSets` | core | the catalog, plus curated per-surface subsets |
| `WtWrapRenderer` | core | pure markup rendering; the only place text is produced |
| `WtEditingFlags` | ui | registry-backed switches and strategy selection |
| `WtSurroundDescriptor` | ui | the `lang.surroundDescriptor` extension |
| `WtTagSurrounder` | ui | one popup entry, parameterized by catalog entry |
| `WtWrapExecutor` | ui | the swap seam — how the markup actually gets inserted |
| `WtTemplateWrapExecutor` | ui | live-template insertion; mirrors `<section>` names |
| `WtDocumentWrapExecutor` | ui | plain document edit; optional modal prompt |

Registry keys: `wikitext.editing.surround.enabled`,
`wikitext.editing.surround.strategy` (`template` | `document`),
`wikitext.editing.variablePrompt` (`inline` | `dialog` | `none`).

Rather than a separate `WtSectionSurrounder` class, the variable case is a
property of the catalog entry (`variablePrompt` + a `$NAME$` placeholder
appearing in both markers) that every executor handles — so a second
value-taking construct costs one enum entry and no new classes.

Original sketch, retained for the reasoning (mirroring
`GroovySurroundDescriptor` / the Markdown plugin):

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
(`before.wt` + selection markers → `after.wt`) under `wikitext-ui/src/test/`,
one per catalog entry plus the section-template case.

## 2a. Lexing apostrophe quote markup — implemented

Split out from the toggle actions, and done *first*: with real tokens the
toggle actions can detect existing formatting from the token stream instead of
a text scan, so this removed the `WtStyleMarkerScanner` hack the original plan
was resigned to.

MediaWiki decides quote markup purely by the **length** of a run of
apostrophes (Help:Wikitext#Text_formatting): 2 = italic, 3 = bold, 5 = both.
The lexer now maps a run to `TWO_APOS` / `THREE_APOS` / `FIVE_APOS` /
`SINGLE_APOS` — tokens that were already declared in `Wikitext.bnf` (whose
`PLAIN_TEXT` regex already excluded `'`), so no token-type changes were
needed.

**The tokens are named for what was seen, not what it means, and that is the
whole design.** A run's meaning is not knowable at lexing time, because the
*closing* run decides how an opening five-run splits:

```
'''''five''  more '''    ->  italic closes first: <b><i>five</i> more </b>
'''''five''' more  ''    ->  bold closes first:   <i><b>five</b> more </i>
```

Identical prefixes, opposite nesting. A lexer cannot see far enough ahead, and
guessing would bake a wrong answer into the token stream — so it reports the
run length as a fact and leaves pairing to the parser, the only layer that
sees both ends. `quoteNestingAmbiguity.wt` pins exactly this: both lines
produce `FIVE_APOS`, and only the closers differ.

MediaWiki's odd-length quirks are handled in one place (`apostropheRun()`) by
pushing back the markup portion so the same rule re-runs on it:

| Run | Emitted |
|-----|---------|
| 1 | `SINGLE_APOS` (literal — the apostrophe in "don't") |
| 2 / 3 / 5 | `TWO_APOS` / `THREE_APOS` / `FIVE_APOS` |
| 4 | `SINGLE_APOS` + `THREE_APOS` (one literal quote, then bold) |
| 6+ | excess as literal text, then `FIVE_APOS` |

Consequences worth knowing:

- `NOT_DELIM` now excludes `'`, so **`PLAIN_TEXT` runs stop at every
  apostrophe** — "don't" lexes as three tokens. Unavoidable: JFlex prefers the
  longest match, so without it `''italic''` would be swallowed whole. This is
  what `SINGLE_APOS` is for.
- **Scoped to the `WIKI_TEXT` state only.** `TEMPLATE` / `LINK` / `TABLE` have
  their own text char classes that still absorb apostrophes, so quotes inside
  a table cell or link label remain plain text. Converting those is a
  follow-up, deliberately deferred so the blast radius stayed one state.
- The parser accepts the four tokens as **inline leaves**, with no bold/italic
  PSI structure yet. Pair-matching is deferred because unclosed runs are
  common and legal in real wikitext, and a naive pairing rule would
  manufacture error elements across ordinary pages.
- The single-line rule ("formatting works correctly only within a single
  line") is *not* encoded in the lexer. `NEWLINE` is already its own token, so
  the eventual pairing pass can refuse to cross one; doing it in the lexer
  would need state the parser would then have to second-guess.

Test data: `quoteBasics`, `quoteApostrophes`, `quoteNestingAmbiguity`,
`quoteOddRuns` (lexer). Corpus churn was one line in
`parsingTestData.parse.txt` — the only apostrophe in the entire test corpus.
</content>
