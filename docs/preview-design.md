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

## Reference image (transcription workflow)

Proofreading is done against the page's scan, so the preview pane has a
toolbar toggle (`ToggleReferenceImageAction` in `WtEditorWithPreview`) that
swaps the rendered preview for the reference image. The image URL comes from
`VfsBackend.pageImageUrl()`, which points at the sidecar's
`GET /preview/page-image?path=…` — currently a **stub** returning a generated
placeholder SVG labelled with the page title. The real implementation will
resolve the scan through ProofreadPage (`prop=imageforpage`, or the Index's
`File:` plus page number → thumbnail URL) and redirect/proxy to it; since the
plugin only ever dereferences this URL inside JCEF, that swap needs no client
change.
