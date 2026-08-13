# TemplateData-driven editor assistance (future work)

Not scheduled. This records what MediaWiki's
[TemplateData](https://www.mediawiki.org/wiki/Extension:TemplateData) extension
would let us build, and — more usefully in the short term — which seams in the
editing features should be shaped now so that adopting it later is additive
rather than a rewrite.

## What TemplateData gives us

The extension introduces a `<templatedata>` tag on a template's documentation
page and an API that serves the same information as JSON. Per template it
describes: the parameter list, each parameter's label, description, type
(`string`, `wiki-page-name`, `date`, `number`, …), whether it is required or
suggested, its aliases, its default, and the preferred parameter order.
VisualEditor's template dialog is built entirely from this, so the data is
good enough to drive a real UI where wikis have bothered to fill it in.

Two properties matter for us:

- It is **per wiki**. The same template name can carry different parameters on
  en.wikisource.org and on a local test wiki, so anything derived from it is
  site-scoped and belongs behind the sidecar, not in a bundled table in the
  plugin.
- It is **frequently absent**. Plenty of templates have no TemplateData at all.
  Every feature below therefore needs a defined "we don't know" state, in the
  same spirit as `WtTagDisplayKind.UNKNOWN` — show nothing rather than guess.

## Features it would unlock

1. **Documentation on hover / Ctrl+Q** over a `WtTemplate` name: the template's
   description plus its parameter table. A `DocumentationTargetProvider` on the
   template-name element.
2. **Parameter-name completion** inside `{{Foo|…}}` — the highest-value item.
   Offer the not-yet-used parameters, required ones first, with the
   TemplateData description as the completion item's tail text.
3. **Parameter-value completion** where the type says so: `wiki-page-name`
   parameters can complete against page titles the sidecar already has cached.
4. **Template-name completion** after `{{`, from the set of templates known to
   the site.
5. **Inspection**: flag unknown parameter names and missing required
   parameters. Strictly opt-in — a false positive on a wiki with stale
   TemplateData is worse than no inspection.
6. **A "fill template" dialog / live template**, VisualEditor-style: pick a
   template, get a skeleton with its required parameters laid out.
7. **Parameter info** (Ctrl+P) showing the current parameter's description
   while the caret sits in a template argument.

## What we should do now

Nothing user-visible. The point is to avoid decisions that would make the above
awkward:

- **Keep markup generation pure and data-driven.** `WtWrapTag` +
  `WtWrapRenderer` already separate "what the markup is" from "how it gets
  inserted". A future `WtTemplateSkeletonRenderer` fed from TemplateData
  should sit alongside `WtWrapRenderer` with the same shape — pure, unit
  tested, no IDE types — and reuse the same live-template insertion path
  (`WtTemplateWrapExecutor`), which already knows how to insert text with
  mirrored variables. Feature 6 is then mostly a new renderer, not new
  plumbing.
- **Do not hardcode template knowledge anywhere.** `WtTagDisplayClassifier`
  already carries an explicit warning against extending it to templates
  (a template's behaviour is Lua on a specific wiki). TemplateData is the
  correct source; keep the classifier tag-only.
- **Assume the data arrives from wtbot, not from the wiki directly.** The
  preview already goes through the sidecar so credentials, content-model
  awareness and the LAN CA bundle stay server-side, and TemplateData has the
  same constraints plus an obvious caching story (it changes rarely). The
  eventual shape is a `GET /template-data?title=…` router in `src-py/wtbot/api/`,
  a SQLModel cache table, and a `VfsBackend.templateData(path, name)` method
  with a `FakeVfsBackend` implementation so completion is testable offline.
  Completion and hover must degrade to "no data" quietly, and must never block
  the EDT on a network call — the existing pattern is a background fetch that
  fills a cache the provider reads synchronously.
- **Site scoping.** A lookup is meaningless without knowing which site the file
  belongs to. For `wikisource://` files the path already carries that; for
  plain local `.wt` files there is no site, so either the facet
  (`WtFacetType`) or the sidecar's default site has to supply one. Worth
  deciding before the first feature lands, since it affects the signature of
  every provider above.
- **Prototype switches.** Whatever ships first should go behind a
  `wikitext.editing.templateData.*` registry key like the rest of the editing
  features, so it can be turned off without a rebuild.
