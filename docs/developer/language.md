# Wikitext language

Lexer, parser and PSI live in `wikitext/wikitext-core`; highlighting, annotators,
structure view and editing actions in `wikitext/wikitext-language-ui`. Paths
below are relative to `src/main/kotlin/org/limepepper/lang/wikitext/` of those
modules.

## Lexer and parser

| Source | Generator | Output |
|---|---|---|
| `lexer/WikitextLexer.flex` | JFlex, `generateLexer` | `src/main/gen/…/lexer/WtLexer.java` |
| `parser/Wikitext.bnf` | Grammar-Kit, `generateParser` | `src/main/gen/…/parser/WtParser.java`, `…/psi/` (`WtTypes`, `Wt*` PSI interfaces and `impl/`) |

Generated code is committed and never hand-edited. After changing either
source, run:

```bash
GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew :wikitext:wikitext-core:generateLexer :wikitext:wikitext-core:generateParser
```

Only these two grammars are wired into the build. The other `.flex` and `.bnf`
files beside them (`WikitextLexer2/3.flex`, Handlebars, Markdown, Makefile,
Prisma, Dart, `_Html*`/`_Xml*`/`_Dtd*`) are reference material and generate
nothing.

`WtParserDefinition` wires `WtLexerAdapter` and `WtParser` into the `Wikitext`
language (`WtLanguage`); `WtFile` is the file PSI. Hand-written PSI behaviour
is in `parser/WtPsiImplUtil.kt`, `psi/impl/` mixins and `WtElementFactory`.

### Token names must not collide with rule names

Every name in `Wikitext.bnf`'s `tokens=[…]` block must differ from every rule
name in the same file. On a collision Grammar-Kit silently replaces the lexer's
leaf token with the rule's composite element type, and the parse tree quietly
changes shape. This has happened (`HEADING_LINE`, `LINK_TARGET`,
`TEMPLATE_NAME`); check new tokens against existing rules.

### The frame stack

The same character means different things depending on the enclosing
construct. The lexer keeps a stack of `Frame(state, kind, tagName)` entries
with `FrameKind` one of `TEMPLATE`, `TEMPLATE_PARAM`, `LINK`, `LINK_PARAM`,
`TABLE`, `HTML_TAG`, `EXT_TAG`, `VERBATIM`, `HEADING`, `COMMENT`. Opening a
construct pushes a frame and switches JFlex state (`TEMPLATE`, `LINK`,
`TABLE`, `HTML_TAG`, `VERBATIM_TAG`, …); closing pops back to the enclosing
state.

`pipeTokenForContext()` is the canonical example: `|` lexes as `TEMPLATE_PIPE`,
`LINK_PIPE` or `TABLE_CELL_SEP` according to the top frame, and as
`PLAIN_TEXT` outside any construct. Line-start states (`TEMPLATE_BOL`,
`LINK_BOL`, `TABLE_BOL`) handle constructs that only exist at the beginning of
a line.

### Verbatim tags

`nowiki`, `pre`, `source`, `syntaxhighlight`, `score`, `math` and
`templatedata` push a `VERBATIM` frame keyed on the tag name; everything up to
the matching close tag is content, so `{{` inside `<nowiki>` is just text. The
parser exposes the body as `WtVerbatimBody`, which has an element manipulator
so it can host an injection. `WtVerbatimLanguageInjector` injects the
`Latex` language (when a plugin provides it) into `<math>` bodies, wrapped as
`\[ … \]`.

### Apostrophe quote markup

MediaWiki decides quote formatting by the length of an apostrophe run (2 =
italic, 3 = bold, 5 = both). In the `WIKI_TEXT` state, `apostropheRun()` maps
a run to a token named for what was seen:

| Run | Tokens |
|---|---|
| 1 | `SINGLE_APOS` (a literal apostrophe, as in "don't") |
| 2 / 3 / 5 | `TWO_APOS` / `THREE_APOS` / `FIVE_APOS` |
| 4 | `SINGLE_APOS` then `THREE_APOS` |
| 6+ | the excess as literal text, then `FIVE_APOS` |

Odd lengths are handled by pushing back the markup part so the same rule
re-runs on it. The parser accepts the four tokens as inline leaves; there is no
bold/italic PSI yet. Inside templates, links and tables apostrophes are still
plain text, and the syntax highlighter does not colour the quote tokens.

Why tokens describe the run and not its meaning: the closing run decides how
an opening five-run splits (`'''''a'' b'''` is bold-around-italic,
`'''''a''' b''` the reverse), which the lexer cannot see. Pairing belongs to a
later pass that sees both ends — and must refuse to cross a `NEWLINE`, since
MediaWiki formatting is line-scoped. A side effect: `PLAIN_TEXT` runs now stop
at every apostrophe.

## Semantic views

The grammar describes generic tag structure: `<ref>` and `<section>` are both
plain `WtHtmlTag` nodes. `semantics/WtSemanticViews.kt` classifies a PSI
element and returns a transient, typed view:

```kotlin
when (val view = WtSemanticViews.of(element)) {
    is WtReferenceView -> view.tag.openingRange to view.bodyRange
    is WtSectionMarkerView -> view.name to view.boundary   // BEGIN or END
    null -> Unit                                           // ordinary syntax
}
```

`WtTagView` exposes opening/closing/body ranges (absolute document offsets) and
attributes with value ranges. Attribute reading accepts quoted and simple
unquoted values; it is tolerant extraction, not MediaWiki's full attribute
semantics. Self-closing `<ref … />` is classified as a reference reuse even if
unnamed. Section views represent single markers; they do not pair begin/end or
diagnose unmatched labels.

Consumers today: `WtReferenceAnnotator` (reference styling) and the sentence-band
boundary walk (`annotator/WtSentenceBandBoundaries.kt`), which skips reference
bodies.

Views are not PSI. Platform visitors, extension patterns and stub indexes never
see them, so a feature must classify the source PSI at its entry point. Use a
view only within one read action; to keep a reference across edits hold a
`SmartPsiElementPointer` to the source element and classify again.
Navigation, rename or indexing over views would each need their own platform
integration (a `PsiReference` on the source PSI, a stub schema, …); none is
implemented.

The trade-off: fewer grammar and PSI types, at the cost of an explicit
classification call in each semantic consumer.

## Highlighting and annotators

- `highlighting/WtSyntaxHighlighter` maps lexer tokens to `TextAttributesKey`s
  (comments, templates, link targets, template parameters, self-closing tags).
  `highlighting/WtAnnotator` exists but is not registered.
- `annotator/WtSentenceBandAnnotator` is a file-level annotator: it computes
  sentence/clause ranges (`fileSentenceBandRanges`) and applies alternating
  background attributes from a `SentenceBandHighlightingStrategy`.
- `annotator/WtReferenceAnnotator` styles `<ref>` tags as markup and their
  bodies with `WT_REFERENCE_CONTENT`.
- `settings/WtHighlightingSettings` (application service) holds the switches
  and band strength; changing them restarts the daemon in open projects.

## Editing actions

### Markup catalog

`editing/WtWrapTag.kt` (core) is the single catalog of wrappable constructs:
id, title, prefix, suffix, whether it is block-level, and an optional variable
prompt (`SECTION`, whose begin/end markers share a `$NAME$`).
`WtWrapTagSets` holds curated subsets: `surroundWith` (the popup order) and
`toggleable`. `WtWrapRenderer` is the only code that produces markup text; it
is pure and unit-tested. `WtTagDisplayClassifier` (`tags/WtTagDisplayKind.kt`)
classifies tag names as block/inline/unknown; it deliberately does not cover
templates, whose behaviour is wiki-specific Lua.

### Surround With

`editing/surround/` in language-ui:

| Class | Role |
|---|---|
| `WtSurroundDescriptor` | `lang.surroundDescriptor`; permissive element selection so the action is almost never disabled in wikitext; `isExclusive = false` so platform surrounders still show |
| `WtTagSurrounder` | one popup entry per catalog entry |
| `WtWrapExecutor` | the strategy seam |
| `WtTemplateWrapExecutor` | inserts a live template; repeated `$NAME$` mirrors section names |
| `WtDocumentWrapExecutor` | a single document edit, optional modal prompt for the variable |

The variable case is a property of the catalog entry handled by every
executor, so another value-taking construct costs one enum entry.

### Bold / Italic

`editing/WtQuoteToggle.kt` (core) computes the edits; `WtQuoteScanner` finds
quote markers on a line. Removal shrinks a run by the style's length and
deletes it only when nothing is left, which handles five-runs without a special
case. Everything is line-scoped.

`editing/toggle/WtToggleQuoteAction` (with `WtToggleBoldAction`,
`WtToggleItalicAction`) is the IDE plumbing. The shortcuts collide with Go to
Declaration and Implement Methods, so the actions hide themselves outside
wikitext, and `WtEditingActionPromoter` (registered `order="last"`) returns
only our actions when they are among the candidates. Without the promoter the
winner among enabled candidates is undefined.

### Registry switches

`editing/WtEditingFlags` reads the `wikitext.editing.*` registry keys declared
in `wikisource.wikitext-language-ui.xml`. Registry keys, not settings: each
switch selects between competing prototypes, and the losing implementation is
meant to be deleted along with its key.

## Tests

Lexer and parser tests are data-driven from `wikitext-core/src/test/testData/`;
see [Testing](testing.md).
