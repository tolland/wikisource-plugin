# Reference scans: identity, renditions, and alternative sources

Status: **design note. Nothing here is implemented, and nothing here is
proposed for implementation now.** The purpose is to record what the current
implicit model is, what it forecloses, and the small number of things worth
doing so the interesting future stays reachable.

The motivating requirement, stated plainly: *I start transcribing against one
scan, and later a much better scan turns up.* Today that is not a supported
operation — it isn't even an expressible one, because nothing in the system
has a name for "the scan this transcription is being made against". Making it
expressible later is cheap; retrofitting it after a few thousand annotations
exist is not.

Split out of `docs/api-rationalization-proposal.md` §2.10, which raised the
narrower version of this (annotations keyed to a page rather than an image).

## 1. What exists today

There is no noun for the image. There is a set of URL columns on the page's
metadata row, and an endpoint that rewrites one of those URLs:

| Where | What it holds |
|---|---|
| `PageMeta.source_image_url` | full-size page raster URL, from `imageforpage` at fetch time |
| `PageMeta.thumb_url`, `thumb_width`, `thumb_height` | the small rendition |
| `PageMeta.raster_path`, `thumb_path` | local paths, for the future ddjvu/pdftoppm cache |
| `PageMeta.page_number` | this page's number within the backing file |
| `IndexMeta.page_count` | total pages per the Index's pagelist |
| `FileBlob.file_sha1`, `upload_timestamp` | binary identity of a fetched File: — the one real identity handle in the system |
| `GET /preview/page-image?path=&width=` | serves it, rewriting the `page{N}-{W}px-` token to synthesise a width |
| `ScanAnnotation(page_pk, annotation_id, x, y, w, h)` | boxes, keyed to the *page* |
| `FileMeta.crop_x/y/w/h`, `source_page_number` | crop provenance "in source raster pixels" |

Read as a whole: the model says *a page has some URLs*. It does not say which
raster those URLs resolve to, what coordinate space the numbers alongside
them are in, or that the answer could ever change. Three different concepts
are collapsed into those columns, and the collapse is what blocks everything
below.

## 2. The three concepts hiding in "the image"

**A source.** A provenance: one version of one backing file — `File:Foo.djvu`
on some wiki, at some upload. Two uploads of `File:Foo.djvu` are two sources
even though the title is identical, and a Commons scan of the same edition is
a third. `FileBlob.file_sha1` + `upload_timestamp` is exactly the handle for
this, and nothing currently uses it that way.

**A rendition.** One page of one source, rasterised at one width. This is
what a URL actually points at and what a client actually displays.

How many exist per source is **site-dependent, and this is a trap**. A stock
MediaWiki/ProofreadPage install renders any requested width on demand, so a
local wiki behaves as though renditions are free. Wikimedia production does
not: off-bucket widths are refused outright with

> Use thumbnail sizes listed on https://w.wiki/GHai

so the set of valid renditions upstream is a fixed, configured list, not an
open range. Any model of renditions has to treat the allowed widths as a
per-site property rather than as "whatever you ask for" — which is a second,
independent reason renditions want to be a modelled thing rather than a
string rewrite.

**A choice.** Which source this logical page is currently being transcribed
against. Today this is implicit and singular: whatever the fetch worker last
wrote into `PageMeta`. The requirement in the opening paragraph is precisely
the ability to change this choice — which needs it to be a thing that exists
before it can be changed.

Everything that follows is a consequence of these three being one thing.

## 3. What it costs today

**Coordinates have no declared space.** `ScanAnnotation`'s docstring says
scan-pixel coordinates "independent of any on-screen zoom", but what the
client is served is a width-parameterised rendition, and no column records
which width the numbers were captured against. `FileMeta.crop_x/y/w/h` has
the same ambiguity — its docstring says "source raster pixels", which is a
different space again if the client was displaying a thumb. Two independent
consumers, one undeclared convention.

**Synthesised widths are not portable.** `_rendition_url()`
(`wtbot/api/page_image.py:59`) produces a URL for any requested width by
rewriting the `page{N}-{W}px-` token. That is valid against a local wiki and
invalid against Wikimedia, which only serves bucketed sizes. Two things keep
this latent rather than live: the sidecar only ever *asks the API* for two
renditions — the default ~1280px reference image and a 240px thumb
(`PAGE_THUMB_WIDTH`, `wtbot/wiki/client.py:35`), both server-blessed — and the
plugin never passes `width` at all (`VfsBackend.pageImageUrl` has no width
parameter). The first zoom control built against upstream is what would find
it. Worth fixing when renditions get modelled, not before: the fix is to pick
from a known-valid set rather than to compute a URL.

**The bytes cache cannot see a re-upload.** `_cache_path()` in
`wtbot/api/page_image.py:71` keys on `{page_pk}-{width}.{ext}`; the URL
contributes only its file extension. Once a page's rendition is cached, a new
upload of the backing file is never picked up — the old bytes are served
indefinitely, and clearing `blob_root` by hand is the only cure. This is a
live bug rather than a latent one, and it exists specifically because the
cache has no image identity to key on. It is also the cheapest possible
demonstration of the whole problem.

**Annotations drift silently.** A re-upload or a page inserted mid-file gives
the same page title different pixels. Every box still resolves, still renders,
and now points somewhere else. Nothing errors, so nothing surfaces until
someone notices the boxes are a page out.

## 4. The requirement: swapping in a better scan

Suppose the swap were supported. What does it actually involve?

- **Page numbering differs between sources.** Different front matter, plates,
  or missing leaves mean logical page *n* of the work is a different physical
  page in each scan. ProofreadPage already models this on the wiki side (the
  Index's pagelist maps logical to physical), so a per-source page-number
  mapping is the shape to copy, not invent.
- **Pixel coordinates do not survive.** A different scan has different
  dimensions and a different crop of the page. Fractional coordinates at least
  land in roughly the right region and are worth having for that reason;
  pixel coordinates are meaningless across sources.
- **A swap must not silently remap.** The honest outcome is "these 340 boxes
  were drawn on a scan you are no longer displaying" — annotations stay
  attached to the source they were drawn on, and the client offers to
  re-register or discard them. Auto-remapping would reproduce the current
  silent-drift failure with extra steps.
- **The transcription text is unaffected.** Text is the wiki's; only the
  scan-anchored artifacts (annotations, box links, `FileMeta` crops, OCR
  provenance) are source-bound. That is a small, enumerable set, which is
  what makes the swap tractable at all.

### Where the correspondence could live

"This work has an alternative scan at X" is a claim that has to be stored
somewhere, and the options differ mostly in who else benefits:

| Where | Pro | Con |
|---|---|---|
| Client only (IDE settings) | zero backend work; trivially reversible | dies with the workspace; invisible to the sidecar, so OCR and annotations can't use it |
| wtbot model | the sidecar already knows about sources; annotations can FK to it; survives reinstalls | private to one user's install |
| Wiki-side (ProofreadPage extension, gadget, Commons structured data) | shared with every transcriber; the correspondence is genuinely public data | needs buy-in and infrastructure we don't control; slowest path by far |

These are not exclusive, and the sensible order is the order of the table:
wtbot is the pragmatic home for the correspondence, and a wiki-side
representation — if one ever exists — becomes another *source* of the same
claim rather than a replacement for the model. The important part is that the
model has somewhere to put it.

## 5. What to do now to keep it reachable

None of these implement alternative sources. They are the moves that stop the
door closing, cheapest first.

0. **Treat the valid width set as per-site data**, not as an assumption. This
   is the item the local-vs-upstream difference above turns into a
   requirement; everything else in this list is unaffected by it.
1. **Normalise coordinates** to fractions of the page raster, for
   `ScanAnnotation` and `FileMeta` crops alike. Independent of everything
   else here, fixes the live ambiguity in §3, and is a precondition for
   coordinates meaning anything across sources. Migration plus a client
   change; the only item here worth doing on its own merits.
2. **Key the bytes cache on the image, not the page.** Fold the source URL (or
   the file sha1, once recorded) into `_cache_path()`. Fixes the stale-cache
   bug and is a two-line change.
3. **Record what a box was drawn on.** Source identity + page number captured
   at draw time. This migrates nothing and changes no behaviour — it makes
   staleness *detectable*, which is the property that turns a silent drift
   into a question the client can ask.
4. **Don't bake "one image per page" into the wire.** `GET
   /preview/page-image?path=&width=` has no way to say *which* source, and
   every client call site currently assumes there is only one. Leaving room
   for an optional `source=` — unused and single-valued today — costs nothing
   now and avoids a breaking change later.
5. **Return the source identity with the image.** Additive response field, so
   a client can tell whether the annotations it holds belong to the scan it is
   displaying.

## 6. Target model, when it is time

Sketch, not a proposal:

```
ScanSource     one version of one backing file
               (site, file title, file_sha1, upload_timestamp, page_count)

ScanRendition  one page of one source at one width — the cache's real key.
               Rows exist for widths the site will actually serve, rather
               than being synthesised per request.
               (scan_source_pk, page_number, width, url, local_path)

PageScan       a logical page's choice of source, plus that source's
               page number for it — the many-to-many with a "current" flag
               (page_pk, scan_source_pk, source_page_number, is_current)
```

`ScanAnnotation` and `FileMeta` crops then key on `(scan_source_pk,
source_page_number)` rather than `page_pk`. `PageMeta`'s URL columns become a
denormalised view of the current `PageScan` — which is what they already are,
minus the ability to name what they point at.

Worth noting how close the existing tables already are:
`PageMeta.source_image_url`/`thumb_url`/`thumb_path`/`raster_path` is a
`ScanRendition` row that was flattened into its parent, and `FileBlob` is most
of a `ScanSource`.

## 7. Not now, and why

- **No table changes in this pass.** The annotation surface has few enough
  users that the retrofit stays cheap; the point of writing this down is to
  know when that stops being true.
- **No wiki-side work.** An extension or gadget for scan correspondence is a
  community proposition, not a plugin change, and it is only worth raising
  once the local model can represent what it would say.
- **No automatic re-registration of annotations across sources.** Image
  registration is a real problem and a bad thing to do badly; the useful 90%
  is telling the user their boxes are from a different scan.

## 8. Open questions

- Where does the per-site valid-width set come from — `siteinfo`, a
  configured list, or discovered by trying? (`siteinfo` exposes
  `thumblimits`, which is probably the answer, and would sit naturally
  alongside the existing per-site namespace-role resolution.)
- Fractional coordinates relative to *what* — the full page raster, or the
  displayed rendition's box? The former is stable, the latter is what the
  client measures. (The former, with the client converting, is almost
  certainly right.)
- Does a source need to be a wiki file at all? Local ddjvu/pdftoppm extraction
  and pasted screenshots are both already in the model's future
  (`PageMeta.raster_path`, `FileOrigin.paste`), so `ScanSource` probably wants
  a kind discriminator rather than a hard File: dependency.
- Is "current source" per page, or per Index? Per Index matches how someone
  actually finds a better scan (a whole new upload of the whole work), but per
  page is what the annotations key on. Likely: choice at Index level, identity
  at page level.
