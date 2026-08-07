# Prompt: make the wtbot API base URL switchable at runtime

The following is a self-contained task prompt for an implementing model working in
this repository. It encodes the findings of an investigation into why the current
settings screen does not take effect, and a plan for fixing it.

---

## Task

Make the IntelliJ plugin's wtbot API base URL (and request timeout) genuinely
switchable at runtime from the settings screen, without restarting the IDE, and
handle the caches and open editors that currently keep serving content from the
old backend after a switch.

## Background / current behavior

The plugin talks to the wtbot FastAPI sidecar through the `VfsBackend` interface
(`wikitext-vfs/src/main/kotlin/org/limepepper/lang/wikitext/vfs/backend/VfsBackend.kt`),
implemented by `HttpVfsBackend`. Day-to-day there is one sidecar on a fixed
localhost port (18574), but for development and testing we need to switch between
backends (e.g. a local dev server vs the docker-compose harness on another port)
without restarting IntelliJ.

A settings screen exists (`WtbotProjectConfigurable`, backed by
`WtbotProjectSettings`) and it persists host/port/timeout and publishes a
`WtbotSettingsListener` message-bus event on change — but the live VFS keeps using
the base URL it started with.

## Root cause (verified — do not re-derive)

`WtVfsService`
(`wikitext-vfs/src/main/kotlin/org/limepepper/lang/wikitext/vfs/backend/WtVfsService.kt`)
is an **application-level** service and constructs its backend with the
hardcoded-URL constructor:

```kotlin
val backend: VfsBackend = HttpVfsBackend(baseUrl = "http://localhost:18574")
```

Every production consumer — `WtVirtualFileSystem`, `WtVirtualFile`,
`OcrCatalogService`, and roughly a dozen call sites in `wikitext-ui`
(tool window, preview panes, page-nav toolbar, annotation/OCR sync, etc.) —
resolves the backend as `WtVfsService.instance.backend`. The project-aware
`HttpVfsBackend(project)` constructor, which reads `WtbotProjectSettings` and
subscribes to `WtbotProjectSettings.TOPIC` to mutate its `baseUrl`/`timeout`,
is **never invoked in production code** — its only caller is
`WtbotProjectSettingsTest`. So the settings apply and the event fires, but no
live object listens.

There is also a **scope mismatch**: the settings are project-level while the
service and the `wikisource://` `VirtualFileSystem` (and its path→file cache) are
application-level. `VirtualFileSystem` has no project context and VFS paths do
not encode which backend they came from, so per-project backends cannot work
without either putting the backend identity into the VFS paths or accepting that
the last project to apply settings wins. Neither is wanted.

## Design decision (make it this way)

**Move the base-URL/timeout settings to application level.** The sidecar is a
per-machine service, the VFS is application-scoped, and one URL for the whole IDE
matches the real usage. Concretely:

1. Create `WtbotAppSettings` — an application-level `PersistentStateComponent`
   (`@Service(Service.Level.APP)`, `@State(... storages = [Storage("wikitext-vfs-app.xml")])`)
   holding `host`, `port`, `timeoutSeconds`, with the same defaults
   (127.0.0.1 / 18574 / 10) and a `baseUrl` convenience property. Publish changes
   on an **application-level** topic (`ApplicationManager.getApplication().messageBus`),
   e.g. `WtbotAppSettings.TOPIC` with a `WtbotSettingsListener`-style payload.
   Only publish when the effective values actually changed.
2. Rewrite the configurable as an application `SearchableConfigurable`
   (registered under `applicationConfigurable` in the plugin XML for
   `wikitext-vfs`; remove the old `projectConfigurable` registration).
   Keep the current fields; add basic validation (non-empty host, port in
   1..65535, timeout > 0) via `ConfigurationException` in `apply()` instead of
   the current silent catch-and-keep-old-value behavior. A "Test connection"
   button hitting `GET {baseUrl}/health` off the EDT is a nice-to-have, not
   required.
3. Delete `WtbotProjectSettings` and `WtbotProjectConfigurable`, and delete the
   `HttpVfsBackend(project)` and no-arg constructors (note the project
   constructor also leaks its message-bus connection — `connect()` with no
   parent disposable — which disappears with it). `HttpVfsBackend` keeps only the
   primary `(baseUrl, timeout, client)` constructor and becomes effectively
   immutable per instance: remove the settings/topic imports and the internal
   mutation path. One migration nicety: if a project's old
   `.idea/wikitext-vfs.xml` contained non-default values, it is acceptable to
   ignore them (document in the commit message); do not build a migration
   framework.
4. `WtVfsService` becomes the single owner of the switching logic:
   - Build the initial `HttpVfsBackend` from `WtbotAppSettings` at service
     construction.
   - Expose the backend behind a `@Volatile` reference (keep the public
     `val backend: VfsBackend` API as a getter so the ~15 call sites don't
     change; they already re-read `WtVfsService.instance.backend` per
     operation, so swapping the instance is safe).
   - Subscribe to the app-level settings topic (use the application message bus
     with the service as parent disposable — make the service implement
     `Disposable`). On change: build a fresh `HttpVfsBackend`, swap the
     reference, then run the invalidation flow below. A timeout-only change
     should swap the backend but **skip** the invalidation flow.

## Cache/coherence handling on a base-URL switch (the second half of the task)

Things that hold state from the old backend, and what to do about each:

- **`WtVirtualFileSystem.cache`** (path → `WtVirtualFile`, in
  `wikitext-vfs/.../vfs/WtVirtualFileSystem.kt`): do **not** clear the map —
  open editors and the tool-window tree hold these instances, and the IntelliJ
  VFS contract requires path→instance identity, so dropping entries would fork
  identities on re-open. Instead add an `invalidateAll()` (or equivalent) that
  clears each file's cached content/children/metadata so the next access
  re-fetches from the new backend. `WtVirtualFile.invalidateIfStale(stat)`
  already exists for the revid-moved case; add an unconditional variant.
- **Files that don't exist on the new backend**: after invalidating, run a
  `statBulk` against the new backend (reuse the `refresh(asynchronous = true)`
  machinery). For paths where `exists == false`, mark the `WtVirtualFile`
  invalid (`isValid` returns false) and close any editors showing it via
  `FileEditorManager.closeFile` across open projects (on the EDT). Do not leave
  editors silently showing content the new backend doesn't have.
- **Unsaved documents**: `FileDocumentManager` may hold modified documents for
  `wikisource://` files. Their in-memory text and the `revid` used as
  `baseRevid` on save both belong to the old backend; writing them to the new
  backend risks a bogus conflict or a wrong-base edit. Before swapping, collect
  unsaved wikisource documents; if any exist, ask the user (modal dialog:
  "Save to current backend before switching / Discard / Cancel switch").
  Cancel must leave the old backend in place and revert nothing. After a clean
  swap, reload documents for files that survived
  (`FileDocumentManager.reloadFiles` or per-file `reloadFromDisk` equivalents)
  so editors show new-backend content.
- **Ordering**: prompt about unsaved documents first (still on old backend),
  then swap the backend reference, then invalidate + re-stat + close/reload.
  Do the network parts off the EDT, the editor-close/reload parts on it.
- **Tool window tree** (`WikisourceTreeStructure` / `MyToolWindowFactory` in
  `wikitext-ui`): must re-load its roots after a switch. Fire a dedicated
  app-level `WtBackendSwitchedListener` topic from `WtVfsService` after the
  swap+invalidation completes, and have the tool window subscribe and reload.
  This topic is the general hook for anything UI-side (preview panes may also
  want to re-render; treat that as optional polish).
- **`OcrCatalogService`** (`wikitext-vfs/.../settings/OcrCatalogService.kt`):
  inspect it — it caches OCR backend/model catalogs fetched via the backend.
  Clear its cache on the switch topic.
- **`referenceImageUrl`**: composed from `baseUrl` per call, so it self-heals
  once the backend reference is swapped; no action needed beyond any image pane
  refresh that falls out of the reload/re-render above.

## Tests

- Update `WtbotProjectSettingsTest` → app-settings equivalent: setting host/port
  fires the app topic once per effective change; timeout-only change is
  distinguishable (however you encode that — e.g. old+new state in the event).
- New test on `WtVfsService` (or extracted switch logic): after a settings
  change, `instance.backend` targets the new URL (reuse the `HttpServer`
  fixture pattern from `HttpVfsBackendTest`); a timeout-only change does not
  trigger invalidation.
- `WtVirtualFileSystem` test: `invalidateAll` + refresh against a backend
  where a path disappeared marks that file invalid; identity of surviving
  files is preserved (same instance before/after).
- Keep `HttpVfsBackendTest` green — it uses the primary constructor, which
  survives.

## Constraints and conventions

- Kotlin style: class per file for substantial implementations.
- Build/test with a workspace-local Gradle home:
  `GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew :wikitext-vfs:test` and
  `GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew check` before committing.
- Update the stale doc comment in `WtVfsService` ("hard-coded to
  localhost:8000") and `HttpVfsBackend`'s constructor docs.
- Register new services/configurables in the module's plugin XML
  (`wikisource.wikitext-vfs.xml`); grep for the existing registrations of the
  pieces you delete.
- Port conventions: default stays 18574 (docker compose default); tests should
  not assume 18574 is free — bind ephemeral ports as `HttpVfsBackendTest` does.

## Acceptance criteria

1. Changing host/port in Settings and hitting Apply makes the very next VFS
   operation (tool-window expand, editor open, preview render) hit the new URL —
   no IDE restart, no project reopen.
2. Open editors on files that exist on both backends reload to the new
   backend's content; editors on files missing from the new backend are closed;
   unsaved edits trigger the save/discard/cancel prompt and Cancel aborts the
   switch entirely.
3. Timeout-only changes take effect without any cache invalidation or editor
   churn.
4. `GRADLE_USER_HOME="$PWD/.gradle-codex" ./gradlew check` passes.
