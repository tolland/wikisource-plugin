# wtbot API rationalization — proposal

Status: **RFC, phase 1 applied.** The findings below are the survey; the ones
marked **fixed** have been applied (removals and doc corrections that change
no behaviour any client depends on). Everything else still needs agreement
before routes move.

Scope: the HTTP surface only (routers, paths, schemas, error mapping). The
data model (`wtbot/model/`), the VFS tree logic (`wtbot/vfs/`), and the fetch
/ commit workers are out of scope except where the API leaks their internals.

## 1. Where we are

15 routers, 46 paths / 59 operations, ~2580 lines under `src-py/wtbot/api/`
(was 16 routers and 51 paths before the phase-1 removals below).

| Router | Prefix(es) | Routes | Consumer |
|---|---|---|---|
| `health` | — | `GET /health` | both |
| `vfs` | `/vfs` | stat, stat/bulk, children, content ×2 | plugin |
| `preview` | `/preview` | `POST /render`, `GET /page-image` (the only image route) | plugin |
| `page_nav` | `/pages` | `GET /pages/nav` | plugin |
| `annotations` | `/pages` | annotations, text-anchors, box-links (GET/PUT/DELETE ×3) | plugin |
| `ocr` | *(none)* + `/pages` | `/ocr/backends`, `/ocr/models`, `/ocr/config/{name}`, `/ocr/run`, `/pages/ocr/{backends,models,run}` | plugin + admin |
| `page_meta` | `/pages` | `GET /pages/resolve`, `{index,page,file}-meta` under `/pages/{page_pk}` | admin/tests |
| `pages` | `/pages` | `GET /pages/`, `GET /pages/{page_pk}` | viewer/tests |
| `fetch` | `/fetch` | `POST /fetch/`, `GET /fetch/{pk}` | plugin |
| `commit` | `/commits` | list, pending, run-all, run-one, cancel, get | viewer/plugin |
| `sites` | `/sites` | site CRUD + credential CRUD | admin/viewer |
| `namespace` | `/namespaces` | list, get | viewer |
| `edit_journal` | `/edit-journal` | list, get | viewer |
| `file_blob` | `/file-blobs` | list, get | viewer |
| `viewer` | `/viewer` | `GET /viewer/indexes`, `GET /viewer/indexes/{page_pk}` | viewer |

What the plugin actually calls (`HttpVfsBackend.kt`, exhaustive): `/vfs/stat`,
`/vfs/stat/bulk`, `/vfs/children`, `/vfs/content` (GET+POST), `/preview/render`,
`/preview/page-image`, `/pages/nav`, `/pages/annotations`, `/pages/text-anchors`,
`/pages/box-links`, `/pages/ocr/{backends,models,run}`. That is **17 of 46
paths**. Everything else is viewer, tests, or admin — which is the main reason
the surface is hard to read: three audiences, one flat namespace, no signal
about which routes are contract and which are conveniences.

## 2. What actually hurts

### 2.1 `/pages` is a five-way shared prefix

`pages`, `page_meta`, `page_nav`, `annotations`, and half of `ocr` all mount
under `/pages` (`page_image` did too, until the cleanup below).

To be precise about the mechanism, because "one router masks another" would be
the wrong description: `include_router()` does not create an isolated
namespace. It splices each router's path operations into one ordered table,
and matching is first-match-wins — the same rule FastAPI documents for two
operations in a single file ("`/users/me` needs to be declared before
`/users/{user_id}`"). Nothing extra happens because the operations arrived
from different modules; the rule just stops being visible in any one file.

That does bite here. `pages` owns `GET /pages/{page_pk}`, which matches any
single segment, so `/pages/nav`, `/pages/resolve`, `/pages/annotations`,
`/pages/text-anchors` and `/pages/box-links` are all live only because
`create_app()` includes `pages.router` last. Verified against the pinned
FastAPI (0.140.0): with the dynamic router included first, `GET /pages/nav`
answers **422**, not 404 — it matched `{page_pk}` and failed to parse `"nav"`
as an int. A 422 on a route that exists is a confusing way to find this out,
which is why `src-py/tests/test_route_order.py` now pins it and `create_app()`
carries the constraint as a comment.

So this is not a latent bug — everything works — but it is a real
comprehension cost: five modules, no single place showing what `/pages` means,
and an ordering rule that is invisible unless you know to look for it. That is
the thing worth fixing (§3, rule 1), not a broken route.

Related, and genuinely confusing rather than merely implicit: `/commits` uses
`{page_pk}` and `{commit_pk}` in **the same path position** —
`POST /commits/{page_pk}` runs a page's pending commit,
`GET /commits/{commit_pk}` fetches a commit row. Two different id spaces, one
URL shape, and no way to tell from the URL which one you hold.

### 2.2 Two addressing schemes, unevenly applied

Everything the plugin holds is a `wikisource://` VFS path. Everything the DB
keys on is a `page_pk`. The API splits along no clear line:

- path-addressed: `/vfs/*`, `/pages/nav`, `/preview/page-image`, `/pages/annotations`,
  `/pages/text-anchors`, `/pages/box-links`, `/pages/ocr/*`, `/preview/*`
- pk-addressed: `/pages/{pk}/index-meta`, `/page-meta`, `/file-meta`,
  `/commits/{page_pk}`, `/viewer/indexes/{page_pk}`
- both: `GET /pages/resolve` exists purely to bridge the two

So a client that wants a page's `PageMeta` must call `/pages/resolve?path=…`
first — an extra round trip to convert an identifier the server could resolve
itself. `page_meta` is currently only exercised by tests and tooling, which is
why nobody has felt this yet; the moment the editor wants page-quality or
short-name data it will.

### 2.3 Duplicate endpoints for the same bytes — **fixed**

`GET /pages/image` and `GET /preview/page-image` both served scan renditions
through the same `serve_scan_image()` helper, differing only in the
no-image-known case: 404 vs a generated placeholder SVG. `page_image.py`'s
docstring called itself "canonical"; the plugin called the other one, and
`/pages/image` had no caller anywhere — not the plugin, not the viewer app,
not the tests.

Resolved: `/pages/image` is gone. `page_image.py` keeps `serve_scan_image()`
as the cache-and-serve engine and no longer defines a router;
`/preview/page-image` is the single image endpoint. A strict (404-on-miss)
mode, if wanted again, belongs there as a query flag.

Similarly `ocr` carries two parallel surfaces — `/ocr/run` (explicit scope +
image) and `/pages/ocr/run` (path → scope + image URL) — with the second a
translation shim over the first. That split is defensible; it just isn't
signposted by the URL structure, and both live in one 366-line module.

### 2.4 Resolve-a-page-leaf boilerplate is copy-pasted

`page_nav.py:49`, `annotations.py:106` (`_page_for`), `ocr.py:273`
(`_page_for` again, different return type) and, until its route was removed,
`page_image.py` each do `PageStore(session)` → `resolve(store, path)` →
`isinstance(node, PageLeaf)` → `raise HTTPException(404, "not a proofread
page: …")`. Two of them are identically-named private helpers in different
modules.

More broadly there are 29 hand-rolled `HTTPException(404, …)` sites. Only
`vfs.py` has a structured domain-error → status map (`_ERROR_STATUS`), and it
is local to that module rather than an app-level exception handler.

### 2.5 Schemas have no home

Response/request models are scattered: 17 in `api/schemas.py`, 11 inline in
`ocr.py`, 9 in `annotations.py`, 3 in `page_meta.py`, 2 each in `page_nav.py`,
`preview.py`, `sites.py`, 1 in `viewer.py` and `fetch.py`.

`schemas.py` is documented as "the VFS contract" but also holds
`CommitRunResponse`, `PendingCommitPage`, and `PendingCommitJournal`, which are
not VFS at all.

Its header also stated "the Kotlin client is generated from that spec". It
isn't — `wikitext-vfs/.../backend/VfsModels.kt` is a hand-maintained mirror,
and `HttpVfsBackend` builds JSON by string concatenation. **Fixed** in the
docstring (the header now says the Kotlin side is a hand-maintained copy that
can drift); closing the gap for real is phase 5.

### 2.6 Table models are the wire contract

29 route handlers declare `response_model=` a SQLModel **table** class (`Page`,
`Site`, `Commit`, `Namespace`, `EditJournal`, `FileBlob`, `IndexMeta`,
`PageMeta`, `FileMeta`, `FetchRequest`, `SiteCredential`). Every column added
to the DB is published to clients automatically, and there's no place to hang
a computed field.

The sharp edge: `GET /sites/{site_pk}/credential` returns `SiteCredential`,
whose `password` column is plaintext by design (`site_credential.py:8-12` —
the model deliberately separates secrets from `Site` "so Site rows are safe to
inspect and log"). The read endpoint hands the secret straight back out. Even
for a localhost dev tool, a `SiteCredentialOut` without `password` costs
nothing.

### 2.7 Stub surface presented as real API — **fixed**

`POST /vfs/rename`, `POST /vfs/delete`, `POST /vfs/child` unconditionally
returned `status="unsupported"`; `GET /vfs/changes` always returned an empty
change list and echoed the cursor. Four unimplemented operations, described in
`/docs` and the OpenAPI spec as if they were contract, with no callers.

Resolved: the four routes are removed. Their schemas stay in `api/schemas.py`
under a new "C) Reserved — designed, not served" section, because they encode
decisions that are expensive to rediscover — above all the rename-identity
invariant (a rename must reach the plugin *as* a rename, never as
delete+create, or every remote rename kills the open editor tab).

### 2.8 Cosmetic-but-real inconsistencies

- Collection roots are declared as `"/"` (`/pages/`, `/commits/`, `/sites/`,
  `/fetch/`, `/namespaces/`, `/edit-journal/`, `/file-blobs/`), so the
  un-slashed form takes a 307. `/vfs/*` and the `/pages/{feature}` routes have
  no trailing slash. Clients must know which is which.
- Plural nouns everywhere except `/fetch` (verb-ish, singular),
  `/edit-journal` (singular), and `/vfs/child` (singular).
- `route_class=DebugLoggingRoute` is applied to 4 routers of 15
  (`vfs`, `preview`, `ocr`, `annotations`) — the rest are invisible to the
  request/response logger.
- ~~`debug_loggig_route.py` is misspelled.~~ **Fixed**: renamed to
  `debug_logging_route.py` (the logger name `wtbot.api.debug_logging_route`
  moved with it — it is what `log_levels` targets).
- ~~`main.custom_openapi()` overrides the spec's metadata with
  placeholders.~~ **Fixed**: removed. It replaced the real
  `FastAPI(title="wtbot", version="0.1.0")` with title `"Custom title"`,
  version `"2.5.0"` and a FastAPI-tutorial description and logo. It also had
  a bug worth recording: it closed over the module-global `app` while being
  assigned to *every* app `create_app()` builds, so any test-built app
  returned the global app's schema rather than its own — the two happened to
  agree, so it never surfaced.
### 2.9 `/viewer/indexes` is misnamed — it is the Index endpoint

`GET /viewer/indexes` and `GET /viewer/indexes/{page_pk}` list Index: pages
(`content_model == "proofread-index"`) with their page counts, and return one
Index's summary plus body. Nothing about either is viewer-specific: that is
simply *the* Index-listing endpoint, sitting under a prefix that names one
consumer of it. The `/viewer` prefix implies "debug UI only, don't rely on
this", which is the opposite of true — an Index listing is the natural entry
point for the tool window's tree too, and today the plugin has to reconstruct
it from `GET /pages/?namespace_role=…` plus its own summarising.

The overlap flagged earlier is therefore not really duplication, it is one
endpoint in the wrong place with a second, cruder path to the same data
alongside it. Two ways to fix, and this is a decision to make rather than a
mechanical rename:

- **Promote it** to `GET /indexes` (or `/pages/indexes`), leaving `/viewer`
  for things that really are debug-UI-shaped. Small wire change; the only
  caller is `viewer/src/lib/api.ts:152,156`.
- **Keep the URL, fix the framing**: rename the module and tag, document it as
  general-purpose, and let `/viewer` mean "read-only summary views" rather
  than "for the SvelteKit app".

Recommended: promote to `/indexes`, since it belongs to the same tier as
`/pages` and `/sites` rather than to a client. Not done yet — unlike the rest
of the applied cleanups this changes a URL a client calls, so it wants a
decision first.

### 2.10 `ScanAnnotation` is keyed to a page, but describes an image

This one is a data-model problem that the API is currently baking in, so it
belongs here even though the fix is not an API fix.

`ScanAnnotation` is `(page_pk, annotation_id)` plus `x/y/width/height`, and
the whole annotation surface is addressed as `/pages/annotations?path=…`. But
a bounding box is not a property of a *page*. It is a property of a specific
raster: one page of one version of one DjVu/PDF, at some coordinate space.
The page is a convenient handle for it — and a wrong one.

Three ways it breaks, in rough order of nastiness:

1. **The backing file changes.** A re-scan, a cleaned-up DjVu, or an OCR-layer
   re-upload gives `Page:Foo.djvu/12` new pixels under the same title. Every
   box on it still resolves, still renders, still looks fine — and now points
   at the wrong part of the scan. Silent wrongness, not an error.
2. **A page is inserted or removed in the file.** Every subsequent page's
   raster shifts by one. The entire index's annotations drift while remaining
   individually "valid". This is the case that would cost the most to clean up
   after the fact, because nothing recorded what the boxes were drawn on.
3. **Coordinate space is unrecorded.** The model docstring says scan-pixel
   coordinates "independent of any on-screen zoom", but what the client is
   served is a width-parameterised thumb rendition (`page{N}-{W}px-`,
   rewritten per request). Nothing in the row says which space the numbers are
   in, so changing the preview width either silently invalidates every box or
   doesn't, depending on client behaviour nobody has written down.

Worth noting: only (3) is a bug we can hit today. (1) and (2) are latent, and
they are the kind that surfaces as "why are all my boxes off by a page" long
after the upload that caused it.

Directions, cheapest first — none of these are proposed for this pass:

- **Normalise coordinates** to 0..1 fractions of the rendition. Kills (3)
  outright, is independent of the rest, and is a migration plus a client
  change. Probably worth doing regardless of what happens to (1)/(2).
- **Record what the box was drawn on.** The minimum useful version is the
  backing file's identity plus page number captured at draw time.
  `FileBlob.file_sha1` and `FileBlob.upload_timestamp` already exist and are
  exactly the handle needed. This does not migrate anything — it makes
  staleness *detectable*, which is the property that actually matters: "these
  40 boxes were drawn on a scan that has since changed" beats silent drift.
- **Model the raster.** A `ScanImage` row per (file version, page number),
  with annotations FK'd to it and `PageMeta` pointing at the current one. A
  re-upload then mints a new `ScanImage`; old annotations stay attached to the
  old one and are visibly stale rather than quietly wrong. This is the honest
  model, and `PageMeta.source_image_url` / `thumb_url` / `raster_path` are
  already a `ScanImage` in all but name.

API consequence either way: keep `?path=` addressing on the annotation
endpoints — it is what the editor holds, and re-addressing them by scan id
would make every caller do a lookup it can't do. But the *response* should
carry the scan identity the boxes belong to, so a client can tell it is
looking at annotations drawn on a scan it is no longer displaying. That is an
additive field, so it does not block anything above.

## 3. Target shape

Organize by **consumer and addressing scheme**, not by model.

```
/health

# Plugin file surface — path-addressed, the VFS contract
/vfs/stat            /vfs/stat/bulk       /vfs/children
/vfs/content         (GET read, POST write)

# Plugin page surface — path-addressed, one page's features
/pages/nav?path=            /pages/image?path=       (moved off /preview)
/pages/annotations          /pages/text-anchors      /pages/box-links
/pages/ocr/{backends,models,run}
/pages/{index,page,file}-meta?path=
/pages/preview              (POST render)

# Index listing — promoted out of /viewer, see 2.9
/indexes                    /indexes/{page_pk}

# Job surfaces — server-side work with status
/fetches                    /commits

# Configuration
/sites  (+ /sites/{pk}/credential)      /ocr/backends, /ocr/config/{name}, /ocr/run

# Raw row access, explicitly second-class: viewer + tests only
/objects/pages   /objects/namespaces   /objects/edit-journal   /objects/file-blobs
/viewer/*
```

The rules that fall out:

1. **One prefix, one router.** `/pages` becomes a single package
   (`api/pages/{nav,image,meta,annotations,ocr}.py`) mounted by one parent
   router. The first-match ordering rule from §2.1 does not go away — it
   becomes readable, because one file shows the whole `/pages` table instead
   of it being an emergent property of `create_app()`'s include order.
2. **Path is the client-facing identifier.** Every route the plugin calls takes
   `?path=`. `page_pk` addressing is confined to `/objects/*` and `/viewer/*`.
   `/pages/resolve` stops being a required round trip (it can stay as a
   debugging convenience).
3. **One shared resolver dependency.** `PageLeafDep = Annotated[PageLeaf,
   Depends(resolve_page_leaf)]` replaces the copies; the 404 lives in the
   dependency.
4. **App-level exception handlers.** Move `vfs._ERROR_STATUS` to a
   `VfsError` handler registered in `create_app()`, and give the page-scoped
   errors the same treatment. Handlers, not 29 inline raises.
5. **Explicit response models.** No table class as a `response_model`. Start
   with the credential read; do the rest opportunistically.
6. **Schemas next to their surface.** `api/schemas.py` becomes
   `api/schemas/{vfs,commit,pages,ocr}.py`; inline models move in with them.
7. **Uniform paths.** No trailing-slash collection roots, plural nouns
   throughout, `DebugLoggingRoute` as the default route class for the whole
   app rather than per-router opt-in.

### Open choices to settle first

- **Where the Index listing lives** (§2.9): promote to `/indexes`, or keep the
  URL and re-frame `/viewer`. Recommend promote. **Needs a decision** — it is
  the one finding from this pass that was left unapplied.
- **Annotation identity** (§2.10): normalise coordinates now, record scan
  identity, or model `ScanImage` properly. Recommend normalising coordinates
  regardless (independent, cheap) and adding scan identity to make staleness
  detectable before the annotation surface gets more users.
- **Page-meta by path.** One `/pages/meta?path=` returning a union, or three
  routes (`/pages/index-meta`, `/pages/page-meta`, `/pages/file-meta`)? Three
  keeps the response models flat and the roles distinct; recommend three.
- **`/objects/*` prefix.** Cheap and honest about the tier, but renames
  `/pages/` (viewer + `test_object_api.py`). Alternative: leave them where they
  are and only tag them `deprecated`/`include_in_schema=False`-adjacent in the
  spec.
- ~~**Change feed.**~~ Settled and applied: routes deleted, schemas kept as
  the design record (§2.7).

## 4. Migration order

Each phase is independently shippable; phases 1–2 break nothing.

**Phase 1 — no functional change. DONE**, except where noted.
Removed `custom_openapi()` (placeholder metadata + the global-`app` bug).
Renamed `debug_loggig_route.py` → `debug_logging_route.py`. Corrected the
`schemas.py` header about Kotlin client generation and split it into
Operations / Commit / Reserved. Deleted the four always-`unsupported` `/vfs`
routes and the caller-less `GET /pages/image`. Added
`tests/test_route_order.py` pinning the `/pages` ordering constraint, and the
constraint itself as a comment in `create_app()`.
*Still outstanding in this phase:* `SiteCredentialOut` (drop `password` from
the credential read) — deferred only because it is a response-shape change
rather than a pure cleanup.

**Phase 2 — internal consolidation.**
Introduce the `resolve_page_leaf` dependency and adopt it everywhere.
Register `VfsError` (and a new `PageResolutionError`) exception handlers.
Split `api/schemas.py` into a package. Move inline models in. Make
`DebugLoggingRoute` app-wide.

**Phase 3 — `/pages` becomes one package.**
`api/pages/` with a parent router; no external path changes, so the Kotlin
client is untouched. Move `/preview/page-image` to `/pages/image` (it is a
page's bytes, not a preview concern) and fold `preview/render` in as
`/pages/preview`.

**Phase 4 — addressing cleanup (the only client-visible break).**
Path-addressed meta routes; the Index-listing promotion from §2.9;
`/objects/*` (or the deprecation alternative); trailing-slash normalization.
Land the Kotlin
`HttpVfsBackend` change in the same commit — it's hand-written, so there is no
generated-client step, and 17 call sites are the entire blast radius.

**Phase 5 — optional.**
Generate `VfsModels.kt` from the OpenAPI spec so the mirror can't drift, or
formally document it as hand-maintained and add a contract test that diffs the
spec against the Kotlin models.

## 5. Not proposed

- No change to the SQLite/WAL discipline or the fetch/commit model
  (`src-py/DESIGN.md` stands).
- No versioning prefix (`/v1`). Client and server ship together from this repo;
  a version prefix would buy nothing.
- No async/await conversion. Orthogonal, and the sync-SQLModel handlers are
  fine at this scale.
