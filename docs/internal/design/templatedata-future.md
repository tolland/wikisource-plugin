# TemplateData-driven editor assistance

Not scheduled. What MediaWiki's
[TemplateData](https://www.mediawiki.org/wiki/Extension:TemplateData) would let
the editor do, and which seams to keep clean so adopting it is additive.

## What TemplateData provides

Per template: the parameter list with label, description, type (`string`,
`wiki-page-name`, `date`, `number`, …), required/suggested flags, aliases,
default and preferred order. VisualEditor's template dialog is built from it.

- It is **per wiki**: the same template name can differ between sites, so the
  data is site-scoped and belongs behind wtbot, not in a table bundled with the
  plugin.
- It is **often absent**: every feature needs a quiet "no data" state, as
  `WtTagDisplayKind.UNKNOWN` does for tags.

## Features it would enable

1. Hover / `Ctrl+Q` documentation on a template name
   (`DocumentationTargetProvider`).
2. Parameter-name completion inside `{{Foo|…}}`, required parameters first —
   the most valuable item.
3. Parameter-value completion for `wiki-page-name` parameters, from titles wtbot
   has cached.
4. Template-name completion after `{{`.
5. An opt-in inspection for unknown or missing required parameters (stale data
   makes false positives likely).
6. A "fill template" skeleton with required parameters laid out.
7. Parameter info (`Ctrl+P`) for the parameter under the caret.

## Seams to keep

- **Pure, data-driven markup.** A future `WtTemplateSkeletonRenderer` sits
  beside `WtWrapRenderer` (pure, unit-tested, no IDE types) and reuses the
  live-template insertion in `WtTemplateWrapExecutor`, which already mirrors
  variables. Feature 6 is then a renderer, not new plumbing.
- **No hardcoded template knowledge.** `WtTagDisplayClassifier` stays tag-only;
  a template's behaviour is wiki-specific Lua.
- **Data comes from wtbot.** Expect a wtbot endpoint with a cache table, a
  `VfsBackend.templateData(path, name)` method and a `FakeVfsBackend`
  implementation so completion is testable offline. Providers read a cache
  filled in the background and never block the EDT on the network.
- **Site scoping.** Managed `wikisource-wtbot://` paths carry their site; plain
  local `.wt` files do not, so something — a facet or wtbot's default site —
  must supply one. Decide this before the first provider, since it shapes every
  provider's signature.
- **Registry switch.** Ship behind a `wikitext.editing.templateData.*` key.
