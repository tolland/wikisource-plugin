# Switching the wtbot API base URL at runtime

Design note for the backend-switching support in `wikitext-vfs`. Written as an
implementation plan; kept as the record of why it is shaped this way.

## The bug this replaced

`WtVfsService` is an application-level service and built its backend with a
hardcoded URL:

```kotlin
val backend: VfsBackend = HttpVfsBackend(baseUrl = "http://localhost:18574")
```

Every production consumer — `WtVirtualFileSystem`, `WtVirtualFile`,
`OcrCatalogService`, and a dozen call sites in `wikitext-ui` — resolves the
backend as `WtVfsService.instance.backend`. The project-aware
`HttpVfsBackend(project)` constructor, the only code that read
`WtbotProjectSettings` and subscribed to its change topic, was never called
outside a test. So the settings page persisted host/port and published its
event, and nothing was listening. (That constructor also leaked its message-bus
connection: `project.messageBus.connect()` with no parent disposable.)

There was also a scope mismatch: the settings were project-level while the
service, the `wikisource://` `VirtualFileSystem`, and its path→file cache are
all application-level, and VFS paths do not encode which backend they came
from.

## Decisions

**Application-scoped settings.** wtbot mediates between MediaWiki backends, so
there is never a need for two sidecars at once; the sidecar is a per-machine
service and the VFS it feeds is an app singleton. `WtbotAppSettings` replaces
`WtbotProjectSettings`; `WtbotConfigurable` (an `applicationConfigurable` under
Tools) replaces `WtbotProjectConfigurable`.

**One `baseUrl` string, not host + port.** Deviation from the first draft of
this plan. A single field maps 1:1 onto the launch property below, and lets the
sidecar sit behind https or a reverse-proxy path prefix. `normalizeBaseUrl`
validates scheme/host and strips the trailing slash; persisted garbage is
sanitised back to the default on load rather than left to break request
building.

**One event per edit.** `WtbotAppSettings.update(baseUrl, timeoutSeconds)` sets
both fields and publishes at most one `TOPIC` event. Separate setters (what the
old code had) would fire twice for one Apply and drive two cache invalidations.
The event carries `(previous, current)` so a base-URL switch is distinguishable
from a timeout tweak.

**Immutable backend, swapped by the service.** `HttpVfsBackend` lost its
mutable `baseUrl`/`timeout` and its two extra constructors. `WtVfsService` holds
the live instance in a `@Volatile` field and replaces it on a settings change.
Mutating a shared backend in place would repoint the destination while leaving
every cache filled from the old sidecar silently intact — the swap is the thing
that gives `WtBackendSwitcher` a hook to run.

## Cache coherence on a switch

The sidecar's SQLite database *is* the state; everything plugin-side is a cache
of it that rebuilds quickly. `WtBackendSwitcher` therefore does the blunt thing,
and only takes care over what the user can see:

- **Unsaved documents** are prompted for **before** the swap (Save / Discard /
  Cancel), so "Save" still writes to the sidecar the buffer was read from — the
  cached revid is a conflict token for that sidecar alone, and carrying it
  across would either conflict spuriously or land an edit on a same-named page
  of a different wiki. Cancel resets the settings fields and aborts; it is a
  choice, not a misconfiguration, so no `ConfigurationException`.
- **`WtVirtualFileSystem.cache` is not cleared.** Open editors and the tool
  window hold those instances and the VFS contract requires one instance per
  path, so dropping the map would fork identities on the next lookup. Instead
  `rebindToCurrentBackend()` drops each file's content/children and re-stats
  them all in one `statBulk`.
- **Paths absent from the new backend** are evicted from the cache, their
  editors closed, and the instances marked invalid — in that order, since an
  editor over an invalid file fails its next read with nothing the user can act
  on.
- **Surviving files with a loaded document** are reloaded via
  `FileDocumentManager.reloadFiles`; everything else refetches lazily.
- **A new backend that is unreachable** leaves files valid with caches dropped,
  so the next access surfaces the connection error normally.
- `OcrCatalogService`'s discovered catalog is cleared (OCR backends are
  configured per site on the sidecar). `referenceImageUrl` needs nothing — it is
  composed from `baseUrl` per call.
- `WtVfsService.BACKEND_SWITCHED` fires on the EDT afterwards; the tool window
  subscribes and reloads its roots.

## Launching against a chosen sidecar

```bash
./gradlew runIde -PwtbotBaseUrl=http://127.0.0.1:18584 [-PwtbotTimeoutSeconds=30]
```

becomes `-Dwtbot.baseUrl=…` / `-Dwtbot.timeoutSeconds=…` on the sandbox JVM;
`WTBOT_BASE_URL` / `WTBOT_TIMEOUT_SECONDS` env vars work for any other IDE
instance. The override is applied over the persisted state on **every** launch,
not just a fresh sandbox — the sandbox keeps its config between runs, so a
first-run-only default would be ignored exactly when switching between the dev
sidecar and the docker harness. It is written into the live state rather than
layered over it, so the settings page shows the URL actually in use and can
still move the running IDE elsewhere.

## Tests

`WtbotAppSettingsTest` (event-once semantics, timeout-only distinguishable, URL
normalisation and rejection, persisted-garbage sanitising, startup override) and
`WtVfsBackendSwitchTest` (settings change replaces the live backend; rebind
preserves instance identity, refetches content, evicts vanished paths, and keeps
files when the new backend is down).

## Not done

Preview panes keep their last-rendered HTML until the next render; they do not
subscribe to `BACKEND_SWITCHED`. The old project-level `.idea/wikitext-vfs.xml`
is not migrated — non-default values there are dropped in favour of the new
application-level setting.
