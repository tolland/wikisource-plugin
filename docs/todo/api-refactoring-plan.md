# wtbot API refactoring — plan

The actionable half of the API rationalization. What the surface looks like
today, and why each of these is a problem, is
`docs/reference/api-contract-inventory.md`; read it first — the section numbers
below refer to it.

Phase 1 (removals and doc corrections that changed no behaviour any client
depends on) is applied and recorded in the inventory's §4. Everything here is
outstanding.

## Target shape

Organize by **consumer and addressing scheme**, not by model.

```
/health

# Plugin file surface — path-addressed, the VFS contract
/vfs/stat            /vfs/stat/bulk       /vfs/children
/vfs/content         (GET read, POST write)

# Plugin page surface — everything here is page-scoped and takes ?path=
# No variable first segment: /pages/{page_pk} is NOT in this surface.
/pages/nav                  /pages/image             (moved off /reference-image)
/pages/annotations          /pages/text-anchors      /pages/box-links
/pages/ocr/{backends,models,run}
/pages/{index,page,file}-meta
/pages/preview              (POST render)

# Index listing — promoted out of /viewer, see §3.7
/indexes                    /indexes/{page_pk}

# Job surfaces — server-side work with status
/fetches                    /commits                 /sync

# Correspondence
/links  /links/works

# Configuration
/sites  (+ /sites/{pk}/credential)      /ocr/backends, /ocr/config/{name}, /ocr/run

# Raw row access, explicitly second-class: viewer + tests only.
# /pages/{page_pk} moves here — that is what frees the /pages prefix.
/objects/pages/{page_pk}   /objects/namespaces   /objects/edit-journal
/objects/file-blobs
/viewer/*
```

The rules that fall out:

1. **No variable first segment under a feature prefix** (§3.1). `/pages/*` is
   the page-scoped, `?path=`-addressed surface and contains no `{page_pk}`;
   numeric row access lives under `/objects/pages/{page_pk}`. This is what
   makes router include order stop mattering, rather than something managed by
   a comment and a test. `/commits` gets the same treatment: one id space per
   prefix.
2. **One prefix, one router.** `/pages` becomes a single package
   (`api/pages/{nav,image,meta,annotations,ocr}.py`) mounted by one parent
   router, so the whole `/pages` table is readable in one file instead of being
   an emergent property of `create_app()`'s include order.
3. **Path is the client-facing identifier.** Every route the plugin calls takes
   `?path=`. `page_pk` addressing is confined to `/objects/*` and `/viewer/*`.
   `/pages/resolve` stops being a required round trip (it can stay as a
   debugging convenience).
4. **One shared resolver dependency.** `PageLeafDep = Annotated[PageLeaf,
   Depends(resolve_page_leaf)]` replaces the three copies of `_page_for`; the
   404 lives in the dependency.
5. **Domain-error handlers, not inline raises.** Move `vfs._ERROR_STATUS` to a
   `VfsError` handler registered in `create_app()` alongside the existing
   `api/errors.py` handlers, and give page resolution the same treatment.
6. **Explicit response models.** No table class as a `response_model`.
7. **Schemas next to their surface.** `api/schemas.py` becomes
   `api/schemas/{vfs,commit,pages,ocr,links,sync}.py`; inline models move in.
8. **Uniform paths.** No trailing-slash collection roots, plural nouns
   throughout.

## Phases

Each phase is independently shippable; phases 2–3 break nothing.

### Phase 2 — internal consolidation

- [ ] **`SiteCredentialOut`** — drop `password` from `GET /sites/{pk}/credential`
      (§3.5). Left over from phase 1 only because it is a response-shape
      change rather than a pure cleanup. Do this first; it is the one item here
      with a security edge.
- [ ] Introduce the `resolve_page_leaf` dependency and adopt it in `page_nav`,
      `annotations` and `ocr`.
- [ ] Register `VfsError` and a new `PageResolutionError` exception handler.
- [ ] Split `api/schemas.py` into a package; move inline models in.

### Phase 3 — `/pages` becomes one package

- [ ] `api/pages/` with a parent router; no external path changes, so the
      Kotlin client is untouched.
- [ ] Move `/reference-image` to `/pages/image` (it is a page's bytes) and fold
      `preview/render` in as `/pages/preview`.

### Phase 4 — addressing cleanup (the only client-visible break)

- [ ] Move `GET /pages/` , `GET /pages/query` and `GET /pages/{page_pk}` to
      `/objects/pages` so no variable first segment remains under `/pages` — at
      which point `test_route_order.py`'s ordering constraint can be *deleted*
      rather than maintained, and `create_app()` loses its load-bearing
      comment.
- [ ] Give `/commits` one id space per path position.
- [ ] Path-addressed meta routes (`/pages/{index,page,file}-meta?path=`).
- [ ] Promote the Index listing out of `/viewer` (§3.7).
- [ ] Trailing-slash normalization.
- [ ] Land the Kotlin `HttpVfsBackend` change in the same commit — it is
      hand-written, so there is no generated-client step, and its 13 call sites
      are the entire blast radius.

### Phase 5 — optional

- [ ] Generate `VfsModels.kt` from the OpenAPI spec so the mirror cannot drift,
      or formally document it as hand-maintained and add a contract test that
      diffs the spec against the Kotlin models.

## Decisions still needed

- **Where `GET /pages/{page_pk}` goes** (§3.1): `/objects/pages/{page_pk}`
  (recommended — frees the `/pages` prefix and uses the tier this plan defines),
  or leave the row routes and move the *features* to top-level `/page-*`
  prefixes instead. Either removes the ambiguity; they differ in which surface
  takes the churn.
- **Where the Index listing lives** (§3.7): promote to `/indexes`
  (recommended — it belongs to the same tier as `/pages` and `/sites` rather
  than to a client), or keep the URL and re-frame `/viewer` as "read-only
  summary views". The only caller is `viewer/src/lib/api.ts`.
- **Page-meta by path**: one `/pages/meta?path=` returning a union, or three
  routes (`/pages/index-meta`, `/pages/page-meta`, `/pages/file-meta`)? Three
  keeps the response models flat and the roles distinct; recommend three.
- **`/objects/*` prefix**: cheap and honest about the tier, but renames
  `/pages/` for the viewer and `test_object_api.py`. Alternative: leave them
  where they are and only mark the tier in the spec.

## Annotation identity (§3.8) — additive, and separable

The full analysis is `docs/design/scan-image-modeling.md`; nothing there blocks
this plan. The two API-side consequences are both additive:

- [ ] Keep `?path=` addressing on the annotation endpoints — it is what the
      editor holds, and re-addressing them by scan id would make every caller
      do a lookup it cannot do. But have the *response* carry the scan identity
      the boxes belong to.
- [ ] Leave room in `GET /reference-image` (later `/pages/image`) for naming a
      source, so the wire contract does not bake in "one image per page".

## Not proposed

- No change to the SQLite/WAL discipline or the fetch/commit model
  (`src-py/DESIGN.md` stands).
- No versioning prefix (`/v1`). Client and server ship together from this repo;
  a version prefix would buy nothing.
- No async/await conversion. Orthogonal, and the sync-SQLModel handlers are
  fine at this scale.
</content>
