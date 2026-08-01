# OCR: backends, engine discovery, and the favourites menu

How a bounding box drawn on a page scan becomes recognized text, and why
the "Run OCR" menu is generated rather than written down.

## The backend contract

All OCR goes through one wire contract, the Wikimedia OCR HTTP API:

```
GET /api?image=<url>&engine=<name>&langs[]=<code>&crop[x,y,width,height]=&rotate=
    -> {"text": "...", "engine": "...", ...}
```

In practice the service on the other end is
[py-ocrapi](https://github.com/tolland/py-ocrapi) — a Python port of the
original PHP Wikimedia OCR — which fronts tesseract, Google Vision and
pix2tex behind that single URL. It fetches the image itself, crops and
rotates it, and for pix2tex converts the result to bytes for the model's
multipart API.

That last point is the reason this design collapsed a layer. pix2tex used
to be its own `OcrBackendKind` here, with a client that downloaded the
image, cropped it with Pillow, and posted the bytes — plus an API token
question wtbot had to answer. All of that is now the backend's job, so
pix2tex is simply `engine="pix2tex"` on a `wikimedia` row, and the
remaining kinds are:

| kind | transport | image | prompt |
|------|-----------|-------|--------|
| `wikimedia` | `GET /api` | URL + server-side crop/rotate | sent, ignored today |
| `token_api` | `POST` JSON | pre-cropped bytes (base64) | yes |

`prompt` is sent to `wikimedia` backends unconditionally. No engine behind
that contract reads one right now, and an unknown query parameter is
ignored — so when a prompt-aware engine does appear, no client changes.

## Why the menu is generated

`GET /api/models` on a stock instance returns *every* language every engine
declares. For Google Vision alone that is several hundred entries and about
200KB of JSON:

```json
{"google": {"ace": "بهسا اچيه / Acehnese / Latn / Mapped / Supports handwriting", ...
```

That list is unusable as a menu and useless as a default. But the set that
matters for any *particular* work is tiny and stable: two or three text
models in the language it is printed in, and an ATR model or two for its
formulae. So the plugin keeps a short, ordered **favourites** list and the
menu is built from that.

### Discovery (`ocrapi.catalog`)

Two endpoints, combined:

- `GET /api/models` — every engine and its declared languages
- `GET /api/available_langs?engine=X` — the subset actually installed
  (tesseract only ships the traineddata it was built with)

We prefer `available_langs` per engine so a menu never offers a language
the backend would reject, and fall back to the declared list when that call
fails — an over-broad list beats no list.

The result is cached per base URL with a TTL (default one hour): it changes
only when the service is redeployed, and discovery sits on the path of
opening a page. Exposed as `GET /ocr/models?scope=` and, for the plugin,
`GET /pages/ocr/models?path=`.

**A discovery failure is a 200 with an `error` field, not a 502.** A
backend that cannot be introspected can still be *run* on its configured
defaults, so failing the whole call would take away a working feature to
report a broken optional one.

### Favourites (plugin side)

An `OcrFavorite` is an engine plus the languages to run it with, and
optionally a pinned backend, a menu label, and a prompt. Everything but the
engine is optional so a favourite can defer to the backend's own configured
defaults — which is why empty languages travel to the sidecar as `null`
rather than `[]`: an empty list would *override* those defaults with "no
languages", and an engine with no language dimension (pix2tex) needs
exactly that deferral.

Two levels, resolved in `OcrFavoritesProjectSettings.effectiveFavorites()`:

- **Application defaults** — most people work on one wiki in one language
  and want the same handful of engines everywhere.
- **Project override** — gated on an explicit flag rather than on the list
  being non-empty, so "this project deliberately offers nothing but the raw
  backends" stays expressible.

Settings > Tools > OCR Favourites edits *one* of these, whichever is in
effect, so what is on screen is always what this project will get. The
engine and language pickers there are populated from whatever a page editor
last discovered (`OcrCatalogService`) — the dialog has no page path of its
own, and a page path is what discovery needs — so both fields stay
free-text-capable for the case where nothing has been discovered yet.

### Menu assembly

On every right-click, `BoxCanvasPopup` crosses the effective favourites
with the backends the site actually offers (`OcrMenuChoice.resolve`).
Resolution happens at build time, so a favourite pinned to a backend that
has been renamed or disabled simply doesn't appear rather than producing an
item that fails on click. When nothing resolves — no favourites yet, or all
of them naming absent backends — the menu falls back to one entry per
configured backend on its own defaults, so the feature is never a dead end.
