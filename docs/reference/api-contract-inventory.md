# wtbot HTTP contract — inventory

What the sidecar serves today, who calls it, and the structural rules that
currently hold. This is the description; the changes proposed on top of it are
in `docs/todo/api-refactoring-plan.md`.

Scope: the HTTP surface only (routers, paths, schemas, error mapping). The data
model (`wtbot/model/`), the VFS tree logic (`wtbot/vfs/`) and the fetch/commit
workers are described in `src-py/DESIGN.md`.

Counted from `src-py/wtbot/api/`: **20 routers, 78 paths, 99 operations,
~5,900 lines.**

## 1. Routers

| Router | Prefix(es) | Routes | Consumer |
|---|---|---|---|
| `health` | — | `GET /health` | both |
| `vfs` | `/vfs` | `stat`, `stat/bulk`, `children`, `content` (GET+POST) | plugin |
| `preview` | `/preview` | `POST /preview/render` (HTML via `action=parse`) | plugin |
| `reference_image` | `/reference-image` | `GET /reference-image` | plugin |
| `page_nav` | `/pages` | `GET /pages/nav` | plugin |
| `annotations` | `/pages` | `annotations`, `text-anchors`, `box-links` (GET/PUT/DELETE ×3) | plugin |
| `locator_index` | `/locator-index` | `page-numbers`, `sections`, `dump` | viewer (plugin planned) |
| `ocr` | — + `/pages` | `/ocr/{backends,models,run}`, `/ocr/config/{name}` (PUT/DELETE), `/pages/ocr/{backends,models,run}` | plugin + admin |
| `page_meta` | `/pages` | `GET /pages/resolve`, `{index,page,file}-meta` (GET/PUT) under `/pages/{page_pk}`, `index-meta/ensure` | admin/tests |
| `pages` | `/pages` | `GET /pages/`, `GET /pages/query`, `GET /pages/{page_pk}` | viewer/tests |
| `fetch` | `/fetch` | `POST /fetch/`, `/fetch/drain`, `/fetch/refresh`, `GET /fetch/queue`, `GET /fetch/{pk}` | plugin/CLI |
| `commit` | `/commits` | list, `pending`, create, run-one, cancel-pending, get | viewer/plugin |
| `links` | `/links` | `propose`, link CRUD, `pairs` CRUD, `pairs/{pk}/{rungs,revisions}`, `pairs/index` | viewer/CLI |
| `works` | `/links/works` | list, `candidates`, track, untrack, get, `propose`, `fetch-history` | viewer/CLI |
| `sync` | `/sync` | `report`, `page-report`, `fetch-assets`, `batches` (+ `approve`/`push`/`abort`/`skip`), `page-batches` | viewer/CLI |
| `sites` | `/sites` | site CRUD, `by-label/{label}`, `delete-plan`, credential CRUD | admin/viewer |
| `namespace` | `/namespaces` | list, get | viewer |
| `edit_journal` | `/edit-journal` | list, get | viewer |
| `file_blob` | `/file-blobs` | list, get | viewer |
| `viewer` | `/viewer` | `GET /viewer/indexes`, `GET /viewer/indexes/{page_pk}` | viewer |

## 2. What each client actually calls

**Plugin** (`HttpVfsBackend.kt`, exhaustive): `/vfs/stat`, `/vfs/stat/bulk`,
`/vfs/children`, `/vfs/content` (GET+POST), `/preview/render`,
`/reference-image`, `/pages/nav`, `/pages/annotations`, `/pages/text-anchors`,
`/pages/box-links`, `/pages/ocr/{backends,models,run}`. That is 13 of 78 paths.

**Viewer** (`viewer/src/lib/api.ts`): `/vfs/{children,content}`,
`/viewer/indexes*`, `/pages*`, `/commits*`, `/sites*`, `/namespaces`,
`/fetch/`, `/ocr/{backends,models,config}`, `/links*`, `/links/works*`,
`/sync/*`, `/locator-index/*`.

**CLI and tests** reach everything else.

Three audiences share one flat namespace, and nothing in a URL says which tier
it belongs to. That is the main reason the surface is hard to read.

## 3. Structural rules that hold today

### 3.1 `/pages` is a five-way shared prefix, and router order is load-bearing

`pages`, `page_meta`, `page_nav`, `annotations` and half of `ocr` all mount
under `/pages`.

`include_router()` does not create an isolated namespace. It splices each
router's operations into one ordered table, matched first-match-wins — the same
rule FastAPI documents for two operations in one file (`/users/me` before
`/users/{user_id}`). Nothing extra happens because the operations came from
different modules; the rule just stops being visible in any one file.

`GET /pages/{page_pk}` and `GET /pages/nav` occupy the same shape: one segment
after `/pages`. `{page_pk}` matches any single segment, so `nav`, `resolve`,
`query`, `annotations`, `text-anchors` and `box-links` are live only because
`create_app()` includes `pages.router` last. Verified against the pinned
FastAPI (0.140.0): with the dynamic router first, `GET /pages/nav` answers
**422**, not 404 — it matched `{page_pk}` and failed to parse `"nav"` as an
int. `src-py/tests/test_route_order.py` pins it and `create_app()` carries the
constraint as a comment.

The same rule applies to `/links`: `works.router` is registered before
`links.router` so `GET /links/works` is not swallowed by
`DELETE /links/{link_pk}`.

Nothing is broken today. The cost is comprehension: five modules, no single
place showing what `/pages` means, and an ordering rule invisible unless you
know to look.

### 3.2 Two addressing schemes, unevenly applied

Everything the plugin holds is a `wikisource://` VFS path. Everything the DB
keys on is a `page_pk`. The API splits along no clear line:

- path-addressed: `/vfs/*`, `/pages/nav`, `/reference-image`,
  `/pages/annotations`, `/pages/text-anchors`, `/pages/box-links`,
  `/pages/ocr/*`, `/preview/*`, `/locator-index/*`
- pk-addressed: `/pages/{pk}/{index,page,file}-meta`, `/commits/{page_pk}`,
  `/viewer/indexes/{page_pk}`, `/links/pairs/{pk}`, `/links/works/{pk}`,
  `/sync/batches/{pk}`
- both: `GET /pages/resolve` exists purely to bridge the two

So a client wanting a page's `PageMeta` must call `/pages/resolve?path=…`
first — an extra round trip to convert an identifier the server could resolve
itself. `page_meta` is currently only exercised by tests and tooling, which is
why nobody has felt this yet.

`/commits` uses `{page_pk}` and `{commit_pk}` in **the same path position**:
`POST /commits/{page_pk}` runs a page's pending commit,
`GET /commits/{commit_pk}` fetches a commit row. Two id spaces, one URL shape,
no way to tell from the URL which one you hold.

### 3.3 Duplicated page-leaf resolution

`page_nav.py:51`, `annotations.py:106` (`_page_for`) and `ocr.py:273`
(`_page_for` again, a different return type) each do `PageStore(session)` →
`resolve(store, path)` → `isinstance(node, PageLeaf)` → `HTTPException(404,
"not a proofread page: …")`. Two are identically-named private helpers in
different modules.

There are ~80 hand-rolled `HTTPException` sites across the routers. `vfs.py`
has the only structured domain-error → status map (`_ERROR_STATUS`), local to
that module rather than an app-level handler — though `api/errors.py` does now
register app-level handlers that log and shape every error response (see
`docs/reference/logging.md` §1.3).

### 3.4 Schemas have no single home

21 model classes live in `api/schemas.py`; the rest are inline in `ocr.py`,
`annotations.py`, `page_meta.py`, `page_nav.py`, `preview.py`, `sites.py`,
`links.py`, `works.py`, `sync.py`, `viewer.py` and `fetch.py`.
`schemas.py` is documented as "the VFS contract" but also holds
`CommitRunResponse`, `PendingCommitPage` and `PendingCommitJournal`.

`wikitext-vfs/.../backend/VfsModels.kt` is a **hand-maintained** mirror of the
wire types — not generated — and `HttpVfsBackend` builds JSON by string
concatenation. The two can drift.

### 3.5 Table models are the wire contract

21 route handlers declare `response_model=` a SQLModel **table** class (`Page`,
`Site`, `Commit`, `Namespace`, `EditJournal`, `FileBlob`, `IndexMeta`,
`PageMeta`, `FileMeta`, `FetchRequest`, `SiteCredential`). Every column added
to the DB is published to clients automatically, and there is no place to hang
a computed field.

The sharp edge: `GET /sites/{site_pk}/credential` returns `SiteCredential`,
whose `password` column is plaintext by design (the model deliberately
separates secrets from `Site` "so Site rows are safe to inspect and log"). The
read endpoint hands the secret straight back out.

### 3.6 Cosmetic-but-real inconsistencies

- Collection roots are declared as `"/"` (`/pages/`, `/commits/`, `/sites/`,
  `/fetch/`, `/namespaces/`, `/edit-journal/`, `/file-blobs/`, `/links/`), so
  the un-slashed form takes a 307. `/vfs/*` and the `/pages/{feature}` routes
  have no trailing slash. Clients must know which is which.
- Plural nouns everywhere except `/fetch` (verb-ish, singular),
  `/edit-journal` (singular) and `/sync` (verb).
- `route_class=DebugLoggingRoute` is now applied to every router, and each tag
  is listed in `KNOWN_DEBUG_ROUTE_TAGS` (`logging_config.py`).

### 3.7 `/viewer/indexes` is misnamed — it is the Index endpoint

`GET /viewer/indexes` and `GET /viewer/indexes/{page_pk}` list `Index:` pages
(`content_model == "proofread-index"`) with their page counts, and return one
Index's summary plus body. Nothing about either is viewer-specific: that is
simply *the* Index-listing endpoint, sitting under a prefix that names one
consumer of it. The `/viewer` prefix implies "debug UI only, don't rely on
this", which is the opposite of true — an Index listing is the natural entry
point for the tool window's tree too, and today the plugin would have to
reconstruct it from `GET /pages/?namespace_role=…` plus its own summarising.

### 3.8 `ScanAnnotation` is keyed to a page, but describes an image

A bounding box is not a property of a *page*. It is a property of a specific
raster: one page of one version of one backing file, at some coordinate space.
`ScanAnnotation` is keyed `(page_pk, annotation_id)` and the whole annotation
surface is addressed as `/pages/annotations?path=…`, so the page is doing duty
as the image's identity — conveniently, and wrongly. It breaks when the backing
file is re-uploaded, when a page is inserted mid-file, and today, because
nothing records which coordinate space the numbers are in.

The full analysis is `docs/design/scan-image-modeling.md`. One item there is a
live bug rather than a latent one: the scan bytes cache keys on
`{page_pk}-{width}`, so a re-uploaded scan is served stale forever.

## 4. Already resolved

Recorded here so they are not rediscovered as findings:

- **Stub routes removed.** `POST /vfs/{rename,delete,child}` returned
  `status="unsupported"` unconditionally and `GET /vfs/changes` always returned
  an empty change list. All four are gone; their schemas stay in
  `api/schemas.py` under "C) Reserved — designed, not served", because they
  encode the rename-identity invariant (a rename must reach the plugin *as* a
  rename, never as delete+create, or every remote rename kills the open editor
  tab).
- **Duplicate image route removed.** `GET /pages/image` and
  `GET /preview/page-image` served the same bytes through the same helper,
  differing only in the no-image case (404 vs a placeholder SVG). `/pages/image`
  had no caller anywhere; the survivor is now `GET /reference-image` with its
  own router holding both the route and the cache-and-serve engine. It is the
  *reference image* — the scan being transcribed, ProofreadPage's
  `imageforpage` — not a preview of anything.
- **`custom_openapi()` removed** (placeholder metadata plus a global-`app` bug);
  `debug_loggig_route.py` renamed to `debug_logging_route.py`; the `schemas.py`
  header corrected (the Kotlin client is *not* generated from the spec).
- **Route-order constraint pinned** by `src-py/tests/test_route_order.py`, with
  the constraint restated as a comment in `create_app()`.
</content>
