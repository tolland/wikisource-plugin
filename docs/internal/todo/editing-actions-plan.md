# Editing actions — remaining work

Shipped: Surround With, Bold/Italic toggles with the `ActionPromoter`, and
apostrophe-quote lexing in wiki text (see
[Editing actions](../../user/editing-actions.md) and
[Wikitext language](../../developer/language.md)).

Rules for everything below: each feature goes behind a `wikitext.editing.*`
registry key read through `WtEditingFlags`; markup text comes only from
`WtWrapRenderer` / the `WtWrapTag` catalog; losing prototypes are deleted with
their key. These features touch only the Document, so they work unchanged on
managed `wikisource-wtbot://` files. Keep them compatible with
`internal/design/templatedata-future.md`.

## Toggle actions for tags

- [ ] `<code>` and `<nowiki>` toggles. `WtWrapTagSets.toggleable` already lists
      `CODE` and `NOWIKI`, but only Bold/Italic actions exist. They need
      tag-aware detection (enclosing tag pair) rather than the quote-run logic,
      and shortcuts that don't fight the platform.
- [ ] Optional: a floating toolbar on selection (`floatingToolbarProvider`)
      offering the same actions.

## Generate table (`Alt+Insert`)

- [ ] `WtGenerateTableAction` added to `GenerateGroup`, enabled only in
      wikitext files.
- [ ] `WtTableMarkupBuilder` in `wikitext-core`: a pure
      `(rows, cols, header, cssClass) -> String` emitting `{| … |}`, unit
      tested; the action inserts it and puts the caret in the first cell.
- [ ] UI: a small dialog (rows, columns, header row, optional
      `class="wikitable"`); later perhaps Markdown's grid picker.

## Quote markup follow-ups

- [ ] Lex apostrophe runs in the `TEMPLATE`, `LINK` and `TABLE` states (only
      `WIKI_TEXT` does today).
- [ ] Bold/italic PSI: a pairing pass that resolves five-runs and never crosses
      `NEWLINE`. Unclosed runs are common and legal, so it must not produce
      error elements.
- [ ] Highlight the quote tokens in `WtSyntaxHighlighter`.
- [ ] Inline rich rendering, in this order: (1) an annotator that sets bold /
      italic font on the content between markers using
      `WtQuoteScanner.styledSpans()` — attributes only, no offset changes;
      (2) only if (1) reads well, folding that hides the markers and opens when
      the caret enters. An unclosed run will restyle the rest of its line,
      which matches MediaWiki.

## Replace within transcription bodies

Find in Files over an attached work (see
[Wikisource browser](../../user/browser.md)) searches and replaces whole files,
so it can edit `<noinclude>` headers and footers that the proofread editor
protects.

- [ ] A body-only replace for attached works (the OCR-misreading workflow,
      e.g. "foree" → "force" across an Index's pages): restrict matches to the
      body range from `ProofreadPageParts`, write through the Document when
      open, otherwise through the managed filesystem with its revision check,
      and report per-file conflicts rather than retrying.
