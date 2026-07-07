# Wikitext preview: rendering options and the chosen design

The split editor (`WtEditorWithPreview` / `WtRenderPreviewBrowser`) needs
server-rendered HTML for the buffer's current, unsaved wikitext. MediaWiki
offers three ways to get that; this note compares them and records why the
plugin uses the action API through the wtbot sidecar.

## The three candidates

### 1. `api.php?action=parse` — the action API's preview call

[API:Parsing wikitext](https://www.mediawiki.org/wiki/API:Parsing_wikitext).
POST `text=<unsaved body>`, `title=<page title>`, `prop=text`, plus
`preview=1`, `disablelimitreport=1`, `disableeditsection=1`. Returns a clean
HTML *fragment* in JSON. This is exactly what MediaWiki core's own live
preview (the `mediawiki.action.edit.preview` module behind the "Show preview"
button when live preview is enabled) sends.

Crucially it is **content-model aware**: passing
`contentmodel=proofread-page` (or letting the wiki infer it from a
`Page:`-namespace title) routes the text through ProofreadPage's
ContentHandler. Verified against en.wikisource.org: posting a
`<noinclude><pagequality level="3" …/></noinclude>…` body returns the
`prp-page-qualityheader quality3` banner and the `pagetext` wrapper — the
same output the Proofread editor's preview shows.

### 2. `index.php?title=…&action=submit` — what the Proofread page editor posts

The browser's Page-namespace editor is MediaWiki's *classic EditPage form*,
which ProofreadPage extends. Its edit form is not one textarea — it is three
(`wpHeaderTextbox`, `wpTextbox1`, `wpFooterTextbox`) plus the page-quality
radio group, and the extension reassembles those fields server-side into a
single `proofread-page` content object. "Show preview" simply re-submits the
whole multipart form with `wpPreview=1` and gets the full edit page back as
HTML.

So the reason the Proofread editor "isn't using the live preview" is
historical/structural, not a capability gap: EditPage's form-post preview
predates the API, already understood the multi-field form, and returns a
complete page the browser can just display. It is **not an API**: the
response is a full skin-wrapped HTML document with no stable contract, it
expects form tokens and session cookies, and scraping the rendered content
back out of it is fragile. Nothing it renders is unavailable via option 1 —
option 1 just wants the *serialized* form of the page
(`<noinclude><pagequality …/>header</noinclude>body<noinclude>footer</noinclude>`),
which is exactly what our editor buffer holds anyway, since the VFS serves
the raw page body.

### 3. `rest.php/v1/transform/wikitext/to/html` — Parsoid

Returns a complete standalone HTML document with stylesheet links, which is
convenient for a browser pane. But it assumes the `wikitext` content model,
so ProofreadPage tags in `Page:` bodies are not guaranteed to render with the
extension's handling; it is also the piece most likely to be missing or
misconfigured on a small self-hosted wiki (our primary target is a local
MediaWiki in a VM). Rejected for now; easy to add later as an alternative
sidecar strategy if Parsoid fidelity is wanted.

## Chosen design

**Option 1, proxied through the wtbot sidecar** rather than called directly
from Kotlin:

```
editor buffer ──POST /preview/render──▶ wtbot (FastAPI)
                                          │ pywikibot: action=parse
                                          ▼
                                        the wiki
◀── {title, html_base64, server, script_path} ──┘
```

* `src-py/wtbot/api/preview.py` — `POST /preview/render` takes
  `{path | title, wikitext}`. A VFS `path` (for `wikisource://` files) is
  resolved to site + title + cached content model; a bare `title` (local
  `.wt` scratch files) parses against the first configured site.
* `WikiClient.render_preview()` (`src-py/wtbot/wiki/client.py`) issues the
  `action=parse` request via pywikibot, so credentials, the LAN CA bundle
  (`WTBOT_WIKI_CA_BUNDLE`), and site configuration stay in the one place that
  already has them — the JVM never needs the wiki in its trust store.
* Kotlin `VfsBackend.renderPreview()` mirrors the endpoint;
  `WtRenderPreviewBrowser` debounces document edits (500 ms), calls it off
  the EDT, and shows the HTML in a JCEF browser (Swing `JEditorPane`
  fallback when JCEF is unsupported). The fragment is wrapped in a shell
  that pulls the wiki's own `site.styles` + `ext.proofreadpage.base` from
  `load.php` and rebases relative URLs via `<base href>`.
* HTML travels base64-encoded because the plugin's minimal `JsonReader`
  does not unescape JSON strings.

Latency note: each preview is a network round trip, hence debounce + a
monotonic request generation so stale responses never overwrite newer ones.
The sidecar caches one `WikiClient` per site so pywikibot setup/login is not
paid per keystroke.

## Editor selection by content model

`WtPreviewEditorProvider` picks the split-editor subclass from the file's
MediaWiki content model via `WtEditorProfile.forFile()` (backed by
`WtVirtualFile.contentModel` / `WtContentModel`):

| content model     | editor                   | reference image | page nav | notes |
|-------------------|--------------------------|-----------------|----------|-------|
| `proofread-page`  | `WtProofreadPageEditor`  | yes             | yes      | editor half is a three-field `WtProofreadPageForm` (header/body/footer) over the serialized buffer; the `<noinclude>` convention is parsed/reassembled by `ProofreadPageParts` and survives round trips |
| `proofread-index` | `WtProofreadIndexEditor` | no              | no       | body renders through `{{:MediaWiki:Proofreadpage_index_template}}` — already reflected in the preview since the sidecar passes the content model to `action=parse` |
| anything else     | `WtWikitextEditor`       | no              | no       | unrestricted fallback (also all local scratch files, which carry no content model) |

The subclasses are deliberately thin stubs: shared wiring stays in the sealed
`WtEditorWithPreview` base, and each subclass is the anchor point where
per-model behavior will grow. The profile also gates the preview toolbar
(no reference-image toggle where there is no scan) and the editor header's
page-navigation row.

## Reference image (transcription workflow)

Proofreading is done against the page's scan, so the preview pane can swap
the rendered preview for the reference image. Both halves of the split editor
carry a permanent inset toolbar instead of actions on the platform's
hover/floating toolbar: the preview pane owns `WtPreviewToolbar` (one toolbar,
two button sets switched by mode via action `update()` visibility — render:
toggle/reload; image: toggle/zoom in/out/reset zoom/send-to-OCR stub), and the
proofread editor's `WtProofreadPageForm` carries `WtPageNavToolbar` across its
top with previous/next page stubs for walking the index. The image URL comes from
`VfsBackend.pageImageUrl()`, which points at the sidecar's
`GET /preview/page-image?path=…`. The endpoint serves the real scan raster by
**proxying** it (a proxy rather than a redirect so a dead upstream URL can
degrade to the placeholder instead of a broken image in JCEF):

1. the cached `PageMeta` URL (populated at fetch time by
   `ProofreadPageProcessor` from `prop=imageforpage`);
2. if that is missing or its fetch fails — older sources often have the
   backing `File:` deleted or replaced with one of a different page count —
   one fail-fast `imageforpage` lookup for a fresh URL, persisted back to
   `PageMeta` on success;
3. otherwise a placeholder SVG labelled with the page title.

Worst case is three single-shot requests (image, API lookup, image), each
with its own timeout and **no retries** — a missing scan costs one round of
that per toggle, never a retry loop. Successful proxied images carry
`Cache-Control: private, max-age=600` so mode toggles don't refetch
megabytes; the placeholder is `no-store`.
