# Editors and preview

Plugin-side design of the split editors, the proofread page editor and the OCR
client, all in `wikisource/wikisource-remote-frontend` (paths relative to
`src/main/kotlin/org/limepepper/lang/wikitext/`). User-facing behaviour:
[ProofreadPage editors](../user/proofread-editors.md) and [OCR](../user/ocr.md).

Backend side: wtbot repository (`../wtbot`), `docs/reference/preview-render.md`
(`POST /preview/render` and why it uses MediaWiki's `action=parse`) and
`docs/reference/ocr.md` (OCR backends and engine discovery).

## Which editor opens

Two `fileEditorProvider`s, both `HIDE_OTHER_EDITORS`:

| Provider | Accepts | Builds |
|---|---|---|
| `editor/prp/PrpFileEditorProvider` (`proofread-page-editor`) | file type `proofread-page` or `.prp` | `PrpFileEditor` |
| `preview/WtPreviewEditorProvider` (`wikitext-preview`) | file type `Wikitext` or `.wt`/`.wiki` | `WtProofreadIndexEditor` or `WtWikitextEditor`, chosen by `WtEditorProfile.forFile()` from the cached content model |

Managed files get their file type from the content model (see
[Managed VFS](vfs.md)), so `Page:` content reaches the proofread provider and
`Index:` content reaches the preview provider. `WtEditorTabTitleProvider` names
tabs with `WtPaths.displayName`.

## Split editor and preview

`preview/WtEditorWithPreview` is a `TextEditorWithPreview` over the platform
text editor and `WtRenderPreviewBrowser`; the Index and Wikitext subclasses are
currently thin. `WtRenderPreviewPane` renders:

- the document text (read in a read action) is posted to
  `VfsBackend.renderPreview(path, title, wikitext)` — `path` for managed files,
  the file name as `title` for local files;
- edits are debounced 500 ms; a monotonic request generation drops stale
  responses;
- the returned fragment is wrapped in a shell that loads the wiki's
  `site.styles` and `ext.proofreadpage.base` from `load.php` and sets
  `<base href>` to the wiki server;
- HTML arrives base64-encoded because `JsonReader` does not unescape JSON
  strings;
- JCEF where `JBCefApp.isSupported()`, otherwise a Swing `JEditorPane`.

The proofread editor has its own copy of this pipeline in
`editor/prp/RenderPreviewPane` (adds zoom and `JcefOpenInBrowserMenu`).

## The proofread page editor

`editor/prp/PrpFileEditor` is a `TextEditorWithPreview` of:

- **`PrpTextEditor`** — wraps the platform text editor over the file's single
  serialized Document. `ProofreadPageParts.tagSpans` finds the
  `<noinclude>`/`<pagequality>` tags; each is a guarded block, followed by a
  `CustomWrap` (soft break) and a divider inlay labelled Header/Body/Footer.
  Unparseable buffers get none of these. It installs `WtPageNavToolbar`
  (previous/next from `VfsBackend.pageNav`) as the editor header and
  `PrpSelectAllAction` (body first, then everything).
- **`PrpPreviewBrowser`** — hosts `ReferenceImagePane` (scan) and
  `RenderPreviewPane` with mode/orientation from `PrpPreviewToolbar` and
  defaults from `PrpPreviewFlags` (registry).

`PrpFileEditor` wires the page's models together:

| Model | Persistence (write-behind, debounced, retried) | Backend resource |
|---|---|---|
| `annotation/BoundingBoxModel` | `WtAnnotationSync` | page annotations |
| `TextRangeModel`, rendered by `WtTextRangeManager` | `WtTextRangeSync` | text anchors |
| `BoxLinkModel` | `WtBoxLinkSync` (404 on delete counts as success; the server prunes links) | box links |

Text range offsets are body-relative; `WtTextRangeManager` translates them
against the guarded header's end offset. `PrpStructureViewBuilder` shows PSI
structure for the text pane and the box list for the scan pane;
`PrpFileEditor` re-broadcasts `STRUCTURE_CHANGED` when focus or preview mode
changes.

`ProofreadPageParts`, `ProofreadPageHeader` and `PageQuality` port pywikibot's
`_decompose_page` / `_compose_page` / `FullHeader`, made strictly lossless:
`<pagequality>` is recognised only at the start of the header section, so
`parse → compose` never drops text. `PageQualityEdit.withLevel` rewrites only
the quality tag (used by `SetPageQualityAction`).

`ReferenceImagePane` fetches scan bytes once via
`VfsBackend.fetchReferenceImage` and draws them on the Swing
`ImageAnnotationPane`/`ImageAnnotationCanvas`.

`inlay/ProofreadInlayProvider` and `ProofreadEditorListener` are present but not
registered.

## OCR client

- `OcrCatalogService` (backend module, project service) discovers backends and
  engines for a page via `listOcrBackends` / `listOcrModels`, caches the last
  result for the settings dialog, and is cleared on a backend switch.
- `OcrFavoritesAppSettings` / `OcrFavoritesProjectSettings`:
  `effectiveFavorites()` returns the project list when
  `useProjectFavorites` is set (even if empty), else the application list.
  Empty languages are sent as `null`, so the backend's defaults apply.
- `editor/prp/OcrMenuChoice.resolve(favorites, backends)` runs at menu-build
  time in `BoxCanvasPopup`; unresolvable favourites are dropped and
  `OcrMenuChoice.defaults(backends)` is the fallback.
- `PrpFileEditor.runOcr` calls `VfsBackend.runOcr` off the EDT and hands an
  `ocr/OcrProposal` to `OcrReviewController` (implemented by
  `OcrReviewService`, which shows it in the **Wikisource OCR** tool window).
  Applying goes through the live range model, so edits made since the request
  are respected.

## Why it is like this

- **Preview via wtbot's `action=parse`.** The wiki renders with its own
  templates and the right content model (ProofreadPage quality banner,
  Index template), and credentials and CA bundles stay server-side.
- **The serialized buffer stays canonical.** One Document holds the whole page
  exactly as MediaWiki stores it, so saving, the VFS and the preview need no
  special cases. The editor adds protection and visual structure around it
  rather than splitting it into separate fields.
- **The scan is Swing, not JCEF.** Proofreading needs zoom well past 100 % and
  OCR needs the pixels to crop; a browser page gives neither cleanly.
- **The OCR menu is generated.** A stock OCR service declares hundreds of
  engine/language pairs; a work needs two or three, so the menu is a short
  favourites list crossed with what the wiki offers.
- **OCR results are proposals.** `OcrReviewController` is the boundary between
  producing text and changing the transcription, so the review UI can change
  without touching producers.
