# Backlog — plugin

Small, unscheduled plugin items. wtbot and viewer items are in the wtbot
repository's backlog (`../wtbot`, `docs/internal/todo/backlog.md`). Anything
that grows past a few lines gets its own file.

## Backend switching

- [ ] Preview panes keep their last render after a backend switch; neither
      `WtRenderPreviewPane` nor `RenderPreviewPane` subscribes to
      `WtVfsService.BACKEND_SWITCHED`.
- [ ] Values in the old project-level `.idea/wikitext-vfs.xml` are ignored in
      favour of the application-level `WtbotAppSettings`. Decide between a
      one-shot import and documenting it as a breaking change.

## Managed VFS

- [ ] Measure request amplification and UI responsiveness: request counts and
      time for startup, opening one file, and refreshing a work. Attribute
      callbacks issue `stat` requests and the family container lists `/`;
      check which run on the EDT and fix with explicit invalidation rules.
- [ ] Everyday-workflow parity check with services configured: undo/redo,
      formatting actions, locator opening, preview and reference-image
      workflows. Add regression tests for anything that fails.
- [ ] Hardening: interrupted directory refresh; a write that times out after
      wtbot may have committed it (needs reconciliation — the timeout test only
      covers failure before the handler runs); other HTTP error statuses; more
      content models and path cases.
- [ ] Create, copy, move, rename and delete are unsupported on managed files.
- [ ] Further grouping and search when a use case appears: File/Template
      views, symbol navigation, tag/template search, backend full-text search.

## Wikisource browser

- [ ] Context-action extension point: replace the fixed popup with an action
      group (e.g. `Wikisource.NodeContextMenu`) whose actions get the selected
      node through a `DataKey` and decide visibility in `update()`. Candidates:
      "Show in MediaWiki", and an in-IDE commit workflow (review dirty pages
      against wtbot's pending commits, push, discard) that today happens
      outside the IDE.
- [ ] Editable properties (`@props` is read-only JSON).
- [ ] Create a subpage from the tree.
- [ ] Rename the tool window: its ID is `MyToolWindow` and the stripe title
      comes from `toolwindow.stripe.MyToolWindow=My Tool Window`. Changing the
      ID affects saved layouts and the integration tests.

## Proofread editor

- [ ] The scan toolbar's **Send to OCR** button only logs "not implemented";
      wire it to the selected region or remove it.
- [ ] `WtRenderPreviewPane` and `editor/prp/RenderPreviewPane` duplicate the
      preview pipeline; consolidate.
- [ ] `highlighting/WtAnnotator` is not registered; delete it or register it.

## Locator index (plugin side)

- [ ] Consume wtbot's locator index: `VfsBackend.lookupPageNumbers` /
      `lookupSections` with `FakeVfsBackend` implementations, and completion
      inside `{{double link|…}}` behind a `wikitext.editing.*` registry key.

## Designs, not scheduled

- `internal/design/work-outlines.md` — labelled/structured navigation of a
  work's scans.
- `internal/design/templatedata-future.md` — TemplateData-driven completion,
  hover docs and inspections.
