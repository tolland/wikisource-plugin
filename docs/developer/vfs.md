# Managed VFS

All remote content is exposed as files of one registered filesystem,
`wikisource-wtbot`, implemented in `wikisource/wikisource-remote-backend`
(package `org.limepepper.lang.wikitext.vfs`). Every read and write is an HTTP
call to wtbot through the current `VfsBackend`.

Backend side — the server's path grammar, node tree, aspects and the `/vfs`
endpoints: wtbot repository (`../wtbot`), `docs/reference/vfs-paths.md`.

## Addresses and paths

```
wikisource-wtbot:///{family}/{code}/{namespace}/{title segments…}[/@{aspect}]
```

- `WtManagedAddress` is the only place URLs are built or parsed
  (`fromPath`, `fromUrl`, `url`, `backendPath`). The URL is a logical
  resource address; it does not name the wtbot instance.
- `WtPaths` splits backend paths without I/O: `aspectOf`, `nodePath`,
  `aspectPath`, `decodeSegment` and `displayName` (used for editor tab titles
  and tree labels). A title is a directory node; the files you open are its
  aspects: `@wikitext` (editable text), `@props` (read-only JSON). `@pages` on
  an Index is a relationship listing, not a directory of files. A title segment
  starting with `@` or `%` is escaped as `%40` / `%25`.
- wtbot's root lists sites as `/{family}/{code}`. The filesystem invents the
  missing `/{family}` directory (`isFamilyContainer`) so every path segment is
  a real VFS directory.

## Resolving files

Use `WtWikiFiles`, never construct a `VirtualFile` yourself:

| Call | I/O | Use |
|---|---|---|
| `find(path)`, `refreshAndFind(path)` | may contact wtbot | resolve off the EDT before opening an editor |
| `pathOf(file)` | none | backend path of a managed file, `null` for local files |
| `contentModelOf(file)`, `revisionOf(file)` | none | cached metadata |

`WtManagedFileTypeOverrider` gives each file the type for its content model
(`WtContentModel`: `proofread-page` → `PrpFileType`, `proofread-index` and
`wikitext` → `WtFileType`, `json`, `sanitized-css`; unknown → `WtFileType`). It
uses cached metadata only, so file-type selection is safe on the EDT.

The Wikisource browser is not built from VirtualFiles. `WikiBrowserNode`
(frontend, `tool/WikiBrowserModel.kt`) is a presentation node keyed by database
id, parent occurrence and path; the same Page can appear under several Indexes'
`@pages`. Opening a node goes through `WtWikiFiles` and `FileEditorManager`, so
every route to a resource lands on the same file ID and Document.
`WtManagedBackendFileSystem.list()` rejects non-hierarchical children (as
`@pages` returns) rather than minting duplicate identities.

## Identity and caching

`WtManagedBackendFileSystem` is a `NewVirtualFileSystem`: the platform's
persistent VFS assigns positive `VirtualFileWithId` IDs and supports reverse
lookup through `ManagingFS`. Persisted records survive restarts.

Per file the filesystem keeps:

- **metadata** from the last `stat`/listing (in memory);
- a **content snapshot** file attribute (`wikisource.wtbot.content`): backend
  identity, content model, revision and database id of the last content read.
  It lets file types, editor profiles and cached text restore with wtbot
  offline;
- a **read version** (the revision the editor's text is based on) and a
  separate **disk version** (the latest bytes read). A refresh or diff that
  reads newer bytes while a Document has unsaved changes must not advance its
  conflict token; `WtManagedDocumentListener` promotes the disk version only
  when the Document actually reloads.

## Saving

`getOutputStream` writes through `VfsBackend.writeContent(path, base64,
baseRevid, databaseId)`, which wtbot records in its edit journal. Results:

- `ok` — the new revision becomes the read version and snapshot;
- `conflict` / `error` / transport failure — the save throws `IOException`,
  the path is marked as a failed write, and `WtManagedSaveRecovery` restores
  the Document's unsaved state after the platform has finished its own
  after-save bookkeeping.

A save is refused before any request when the content revision is unknown,
when the backend changed since the text was read, or when the database
identity is unknown.

### Database identity

Every stat, listing and content response carries wtbot's `database_id`. Writes
send the id they were read against and wtbot rejects a mismatch.
`HttpVfsBackend` sets `requiresDatabaseIdentity` and uses its base URL as
`cacheIdentity`. When a lookup or refresh sees a different database at the same
address, clean Documents reload even if revision and length are identical, and
unsaved Documents keep their original write identity (so their save fails
rather than landing on the wrong database).

## Refresh

- `refresh()` walks only files already in persistent VFS
  (`iterInDbChildren`); it never traverses backend listings, which are
  relationship views.
- `refreshFile(file)` resolves a `CacheAvoidingVirtualFile` (as Find/Replace
  navigation can hand out) to its persistent file before marking it dirty.
- A transport failure is never treated as deletion: `getAttributes` and
  `findFileByPath` fall back to cached records; only `exists=false` from a
  successful stat removes a file.

Create, copy, move, rename, delete, `setTimeStamp` and `setWritable` throw
`IOException`.

## Backend service and switching

`WtVfsService` (application service) owns the live `VfsBackend`, built from
`WtbotAppSettings` as an immutable `HttpVfsBackend(baseUrl, timeout)`. Callers
read `WtVfsService.instance.backend` per operation and never hold it.
`FakeVfsBackend` is the in-memory implementation for tests
(`setBackendForTesting`).

`WtbotAppSettings` (application, `wikitext-vfs.xml`) holds `baseUrl` and
`timeoutSeconds`. `update(baseUrl, timeout)` sets both and publishes at most one
`WtbotAppSettings.TOPIC` event carrying `(previous, current)`.
`normalizeBaseUrl` accepts absolute http(s) URLs with a host, strips a trailing
slash and rejects query/fragment; invalid persisted values fall back to the
default. Startup overrides (`wtbot.baseUrl` / `WTBOT_BASE_URL`,
`wtbot.timeoutSeconds` / `WTBOT_TIMEOUT_SECONDS`) are applied on every load and
written into the live state. User-facing behaviour:
[Connecting to wtbot](../user/connecting.md).

On a settings event `WtVfsService` builds a new backend. If the base URL
changed, `WtBackendSwitcher`:

1. (before Apply, from `WtbotConfigurable`) `confirmPendingEdits()` —
   Save / Discard / Cancel for unsaved managed Documents, so a save still goes
   to the backend the text came from;
2. `rebuildAfterSwitch()` — for each open managed file: `resetConnection`
   (drop metadata and read versions), `refreshFile`, and reload Documents the
   user chose to discard; on `VfsBackendException` cached text is kept;
3. clears `OcrCatalogService` in every open project;
4. publishes `WtVfsService.BACKEND_SWITCHED` on the EDT.

Subscribers: the browser tab (reloads the tree) and `WtAttachedWorkIndex`
(recomputes indexed files). Preview panes do not subscribe.

## Attached works

| Piece | Module | Role |
|---|---|---|
| `discoverManagedWork(backend, seed)` | backend | resolves a Page seed to its Index (via `pageNav`), lists `@pages`, bulk-stats the members and checks they share one database |
| `WtWorkAttachments` | backend, project service | persisted attachments (`.idea/wikisource-works.xml`): canonical addresses, backend identity, database id, last confirmed membership; publishes `CHANGED` |
| `indexableWorkContent(backend, work)` | backend | metadata-only eligibility: real revision (`placeholder=false`) or saved local edit (`dirty=true`) |
| `WtAttachedWorkIndex` | frontend, project service | resolves eligible files in the background; callbacks read snapshots without HTTP |
| `WtAttachedWorkIndexableSetContributor`, `WtAttachedWorkSearchScopeProvider` | frontend | contribute those files as extra index roots and one `Wikisource: <work>` scope per work |

Only individual leaves are contributed: returning directories would let the
indexer visit placeholder pages. The scopes are whole-file; they do not respect
the proofread editor's guarded regions.

## Why it is like this

- **A title is a directory.** A wiki title is often both a page and a parent
  of subpages, and the platform has no node that is both. Flipping a file into
  a directory when its first subpage appears would break open editors, so
  titles are always directories and the stable, openable things are aspects.
- **Platform-managed identities.** Find in Files, indexing, editor restore and
  the file-cache conflict dialog all assume persistent `VirtualFileWithId`
  files. Owning identity ourselves meant re-implementing those, badly.
- **Application-scoped backend.** wtbot already mediates between wikis, so one
  service serves every project, and the VFS is an application singleton.
- **Replace the backend, don't mutate it.** Swapping the instance gives
  in-flight operations a consistent client and gives the switcher a single
  point at which to rebind caches.
- **Database identity on every write.** A replacement database at the same URL
  can have identical titles, revisions and lengths; without the id a stale
  buffer would save into a different wiki's data.
- **`WtManagedSaveRecovery` uses platform internals** (`PersistentFSImpl`,
  `FileDocumentManagerImpl`) to undo the platform's optimistic after-save
  state on build 262. Revalidate it whenever the target IDE changes.
