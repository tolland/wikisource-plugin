# wtbot API rationalization — proposal

Status: **proposal / RFC**. Nothing here is implemented. The goal is to agree
on a target shape for `src-py/wtbot/api/` and a migration order before any
routes move.

Scope: the HTTP surface only (routers, paths, schemas, error mapping). The
data model (`wtbot/model/`), the VFS tree logic (`wtbot/vfs/`), and the fetch
/ commit workers are out of scope except where the API leaks their internals.

## 1. Where we are

16 routers, ~50 routes, 2614 lines under `src-py/wtbot/api/`.

| Router | Prefix(es) | Routes | Consumer |
|---|---|---|---|
| `health` | — | `GET /health` | both |
| `vfs` | `/vfs` | stat, stat/bulk, children, content ×2, rename, delete, child, changes | plugin |
| `preview` | `/preview` | `POST /render`, `GET /page-image` | plugin |
| `page_nav` | `/pages` | `GET /pages/nav` | plugin |
| `page_image` | `/pages` | `GET /pages/image` | — (unused) |
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
`/pages/box-links`, `/pages/ocr/{backends,models,run}`. That is **17 of ~50
routes**. Everything else is viewer, tests, or admin.

## 2. What actually hurts

### 2.1 `/pages` is a six-way shared prefix, and route order is load-bearing

Six routers mount under `/pages`: `pages`, `page_meta`, `page_nav`,
`page_image`, `annotations`, and half of `ocr`. Static segments (`nav`,
`image`, `resolve`, `annotations`, `text-anchors`, `box-links`, `ocr/…`) sit in
the same namespace as `GET /pages/{page_pk}`. It works today only because
`main.create_app()` includes `pages.router` last (`main.py:120-135`). Nothing
records that constraint, and nothing tests it. Adding a `GET /pages/{slug}`
style route, or reordering the include block alphabetically, silently breaks
routes.

Related: `/commits` uses `{page_pk}` and `{commit_pk}` in **the same path
position** — `POST /commits/{page_pk}` runs a page's pending commit,
`GET /commits/{commit_pk}` fetches a commit row. Two different id spaces, one
URL shape.

### 2.2 Two addressing schemes, unevenly applied

Everything the plugin holds is a `wikisource://` VFS path. Everything the DB
keys on is a `page_pk`. The API splits along no clear line:

- path-addressed: `/vfs/*`, `/pages/nav`, `/pages/image`, `/pages/annotations`,
  `/pages/text-anchors`, `/pages/box-links`, `/pages/ocr/*`, `/preview/*`
- pk-addressed: `/pages/{pk}/index-meta`, `/page-meta`, `/file-meta`,
  `/commits/{page_pk}`, `/viewer/indexes/{page_pk}`
- both: `GET /pages/resolve` exists purely to bridge the two

So a client that wants a page's `PageMeta` must call `/pages/resolve?path=…`
first — an extra round trip to convert an identifier the server could resolve
itself. `page_meta` is currently only exercised by tests and tooling, which is
why nobody has felt this yet; the moment the editor wants page-quality or
short-name data it will.

### 2.3 Duplicate endpoints for the same bytes

`GET /pages/image` and `GET /preview/page-image` both serve scan renditions
through the same `serve_scan_image()` helper. They differ only in the
no-image-known case: 404 vs a generated placeholder SVG. `page_image.py`'s
docstring calls itself "canonical"; the plugin calls the other one, and
`/pages/image` has no caller at all.

Similarly `ocr` carries two parallel surfaces — `/ocr/run` (explicit scope +
image) and `/pages/ocr/run` (path → scope + image URL) — with the second a
translation shim over the first. That split is defensible; it just isn't
signposted by the URL structure, and both live in one 366-line module.

### 2.4 Resolve-a-page-leaf boilerplate is copy-pasted four times

`page_image.py:97`, `page_nav.py:49`, `annotations.py:106` (`_page_for`), and
`ocr.py:273` (`_page_for` again, different return type) each do
`PageStore(session)` → `resolve(store, path)` → `isinstance(node, PageLeaf)` →
`raise HTTPException(404, "not a proofread page: …")`. Two of them are
identically-named private helpers in different modules.

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

Its header also states "the Kotlin client is generated from that spec". It
isn't — `wikitext-vfs/.../backend/VfsModels.kt` is a hand-maintained mirror,
and `HttpVfsBackend` builds JSON by string concatenation. Either the doc or the
build should change; right now the file claims a guarantee we don't have.

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

### 2.7 Stub surface presented as real API

`POST /vfs/rename`, `POST /vfs/delete`, `POST /vfs/child` unconditionally
return `status="unsupported"`. `GET /vfs/changes` always returns an empty
change list and echoes the cursor. The change-feed schemas (`Change`,
`ChangeKind`, `ChangesSinceResponse`) are fully specified with a load-bearing
design invariant documented in the module header, and entirely unimplemented.

That's fine as a design record, but it currently reads as shipped API in
`/docs` and in the OpenAPI spec.

### 2.8 Cosmetic-but-real inconsistencies

- Collection roots are declared as `"/"` (`/pages/`, `/commits/`, `/sites/`,
  `/fetch/`, `/namespaces/`, `/edit-journal/`, `/file-blobs/`), so the
  un-slashed form takes a 307. `/vfs/*` and the `/pages/{feature}` routes have
  no trailing slash. Clients must know which is which.
- Plural nouns everywhere except `/fetch` (verb-ish, singular),
  `/edit-journal` (singular), and `/vfs/child` (singular).
- `route_class=DebugLoggingRoute` is applied to 4 routers of 16
  (`vfs`, `preview`, `ocr`, `annotations`) — the rest are invisible to the
  request/response logger.
- `debug_loggig_route.py` is misspelled.
- `main.custom_openapi()` overrides the spec's metadata with placeholders:
  title `"Custom title"`, version `"2.5.0"`, description
  `"Here's a longer description of the custom **OpenAPI** schema"` — clobbering
  the real `FastAPI(title="wtbot", version="0.1.0")` in the published spec.
- `viewer.py`'s index listing overlaps `GET /pages/?namespace_role=…`, with its
  own summary shape.

## 3. Target shape

Organize by **consumer and addressing scheme**, not by model.

```
/health

# Plugin file surface — path-addressed, the VFS contract
/vfs/stat            /vfs/stat/bulk       /vfs/children
/vfs/content         (GET read, POST write)

# Plugin page surface — path-addressed, one page's features
/pages/nav?path=            /pages/image?path=
/pages/annotations          /pages/text-anchors      /pages/box-links
/pages/ocr/{backends,models,run}
/pages/meta?path=           (index-meta / page-meta / file-meta by path)
/pages/preview              (POST render)

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
   router, so shared-prefix collisions are visible in one place instead of
   depending on `include_router` order.
2. **Path is the client-facing identifier.** Every route the plugin calls takes
   `?path=`. `page_pk` addressing is confined to `/objects/*` and `/viewer/*`.
   `/pages/resolve` stops being a required round trip (it can stay as a
   debugging convenience).
3. **One shared resolver dependency.** `PageLeafDep = Annotated[PageLeaf,
   Depends(resolve_page_leaf)]` replaces the four copies; the 404 lives in the
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

- **`/pages/image` vs `/preview/page-image`.** Recommend: keep one path-
  addressed image route with an explicit `?placeholder=true|false` (or an
  `Accept`-driven fallback), delete the other. The strict/lenient split is a
  parameter, not two endpoints.
- **Page-meta by path.** One `/pages/meta?path=` returning a union, or three
  routes (`/pages/index-meta`, `/pages/page-meta`, `/pages/file-meta`)? Three
  keeps the response models flat and the roles distinct; recommend three.
- **`/objects/*` prefix.** Cheap and honest about the tier, but renames
  `/pages/` (viewer + `test_object_api.py`). Alternative: leave them where they
  are and only tag them `deprecated`/`include_in_schema=False`-adjacent in the
  spec.
- **Change feed.** Delete the stub routes and keep the schemas as a design
  record, or implement it? Recommend: delete the routes now (they lie), keep
  `schemas/changes.py` with the module docstring intact.

## 4. Migration order

Each phase is independently shippable; phases 1–2 break nothing.

**Phase 1 — no route changes.**
Fix `custom_openapi()` metadata. Rename `debug_loggig_route.py`. Correct the
`schemas.py` header about Kotlin client generation. Add `SiteCredentialOut`
(drops `password`). Add a routing test that asserts every static `/pages/…`
segment resolves regardless of `include_router` order.

**Phase 2 — internal consolidation.**
Introduce `resolve_page_leaf` dependency and adopt it in the four sites.
Register `VfsError` (and a new `PageResolutionError`) exception handlers.
Split `api/schemas.py` into a package. Move inline models in. Make
`DebugLoggingRoute` app-wide.

**Phase 3 — `/pages` becomes one package.**
`api/pages/` with a parent router; no external path changes, so the Kotlin
client is untouched. Delete the unused `/pages/image` or the duplicate
`/preview/page-image` per the decision above.

**Phase 4 — addressing cleanup (the only client-visible break).**
Path-addressed meta routes; `/objects/*` (or the deprecation alternative);
trailing-slash normalization; drop the `/vfs` stub routes. Land the Kotlin
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
