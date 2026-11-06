# Wikitext editing

The **Wikitext Language** plugin adds MediaWiki wikitext support to any
IntelliJ-based IDE. It works on local files and needs no network service.

## File types

| File type | Extensions | Notes |
|---|---|---|
| Wikitext | `.wt`, `.wiki` | Ordinary wikitext. |
| proofread-page | `.prp` | A ProofreadPage `Page:` body saved locally. Parsed as wikitext; with the Wikisource plugin installed it opens in the proofread editor (see [ProofreadPage editors](proofread-editors.md)), otherwise in the normal text editor. |

Files opened from a wiki through the Wikisource plugin have no extension; they
get the Wikitext or proofread-page type from their MediaWiki content model.

## Highlighting

The lexer highlights comments, template transclusions and their parameters,
internal link targets and self-closing HTML tags. Two annotators add a
presentation layer on top:

- **Sentence and clause bands** — alternating, very light background bands
  over prose, so long transcribed paragraphs are easier to scan sentence by
  sentence.
- **Reference content** — the body of `<ref>…</ref>` is drawn in a secondary
  colour so footnote text stands apart from the running text.

Both are controlled in **Settings → Editor → Wikitext Highlighting**: a
checkbox for references, a checkbox for bands and a band-strength slider
(0–100 %, default 35 %). Turning both off shows plain syntax highlighting.

Apostrophe quote markup (`''italic''`, `'''bold'''`) is recognised by the lexer
but is not yet styled.

## Verbatim tags and injected languages

The content of `<nowiki>`, `<pre>`, `<source>`, `<syntaxhighlight>`,
`<score>`, `<math>` and `<templatedata>` is kept verbatim: braces and brackets
inside them are not parsed as templates or links.

When a plugin providing a `Latex` language is installed (for example TeXiFy),
the body of `<math>…</math>` is injected as LaTeX, so it gets that plugin's
highlighting and completion.

## Structure view

**View → Tool Windows → Structure** (or `Alt+7`) lists the file's top-level
elements in order: headings (`H2: Title`), templates (`{{Name}}`, with nested
templates beneath), internal links (`[[Target]]`) and blocks of text (shown by
their first 80 characters). Selecting an entry moves the caret to it.

## Live templates

Live templates have a **Wikitext** context, which applies to every file parsed
as wikitext (including extension-less remote pages). The bundled set contains
`{{ne` and `{{ne2` (a numbered-equation template with a `<math>` body). The same
template group also carries a few LaTeX snippets (`sump`, `\su`, `matf`,
`inline-mathfrak`, `dfra`, `surr`, `dot-surround`) whose contexts belong to the
LaTeX plugin; they appear only when that plugin is installed.

Manage them under **Settings → Editor → Live Templates → Wikitext**.

## Editing actions

Surround With and the Bold/Italic toggles are described in
[Editing actions](editing-actions.md).

## With the Wikisource plugin installed

Installing the Wikisource plugin changes how wikitext files open: every
Wikitext file, local or remote, opens in a split editor with a rendered preview
beside the text. The preview is rendered by wtbot (see
[Connecting to wtbot](connecting.md)); without a reachable wtbot service the
preview pane shows an error and the text editor works normally.
