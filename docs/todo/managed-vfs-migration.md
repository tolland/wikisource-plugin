# Managed Wikisource VFS migration

Status: prototype in progress; lifecycle/URL compatibility updated 2026-11-01.

Migrate ordinary Wikisource browsing, opening, editing and saving to platform-managed
virtual files. Establish those behaviours before enabling indexing and cross-work
Find/Replace as supported features. Each numbered step is a separate milestone;
its completion checks are the gate for moving on.

Search and replace is postponed. The current deliverable is managed files with
platform-owned `VirtualFileWithId` identities and reproduction of existing plugin
behaviour, verified in seeded IDE integration tests. Do not make indexing, work
attachment or native Find/Replace a prerequisite for this cutover.

Search prototype sources remain available for later diagnosis, but their indexing
contributor, scope provider and static Search Everywhere provider are unregistered.
Startup must not fetch or index the hard-coded Stevenson work.

## Current evidence and limitations

- The original `WtVirtualFileSystem` / `WtVirtualFile` supports editors but does
  not supply platform-managed persistent VFS records.
- Implementing `VirtualFileWithId` with our own allocator is insufficient: an
  experimental ID resolved through `ManagingFS` to an unrelated local file.
  Platform VFS IDs must not come from a plugin-local sequence or backend title PK.
- `WtManagedBackendFileSystem`, based on `NewVirtualFileSystem`, lets the platform
  create persistent records and resolve IDs back to the correct files. Its
  temporary `wikisource-wtbot://` protocol runs alongside `wikisource://`.
- Native Find in Files found content across a bounded work: Index text plus
  20 transcription pages. Complete replacement support is still unverified.
- The replacement notebook stopped before replacing because its Document was
  read-only. Child listings exposed `writable`, but `/vfs/stat` omitted it.
  The API and cached-permission refresh have been corrected and tested; the live
  workflow needs verification after restarting both wtbot and the sandbox.
- Registered `wikisource://` URL lookups now resolve through `WtLegacyUrlFileSystem`
  to the canonical `wikisource-wtbot://` managed file. Restored editor entries are
  saved with canonical URLs. The browser now uses typed `WikiBrowserNode` graph
  occurrences, independent of editor files. The managed-to-legacy save bridge is
  removed; old raw-file classes remain unregistered compatibility/test helpers.

Diagnostics: [replacement notebook](../notebooks/managed-replace.ipynb),
`WtManagedReplaceProbe`, `WtManagedBackendFileSystemTest`, `WtManagedWorkTest`.
Passing fixture tests do not replace verification through the running plugin.

## Validation workflow

Use the [IDE integration suite](../reference/ide-integration-tests.md) as the
repeatable acceptance harness for this migration. Build on `@WithWtbot`,
`WtbotServerExtension` and the seeded `ide/en` scenario: each test gets a fresh
database, blob store and temporary project, using the managed API on port 18594.
The current `seededBackendIsVisibleInDebugWindow` test establishes connectivity
and seed visibility, not completion of any managed editor milestone.

Agent IDE launches use a separate display to avoid interfering with the desktop.
For the current watched session, use `DISPLAY=:88`; otherwise use `xvfb-run -a`:

```bash
# Default startup/editor/tool-window smoke test
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTest

# Existing seeded backend check (tagged extended)
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTestExtended --tests '*seededBackendIsVisibleInDebugWindow*'

# All extended scenarios, including migration scenarios as they are added
GRADLE_USER_HOME="$PWD/.gradle-codex" xvfb-run -a ./gradlew integrationTestExtended
```

The default task excludes `extended`; it does not run the seeded check. Follow
the suite's existing tagging convention for new migration scenarios and use a
focused `--tests` selector during development. Run the default smoke test and the
relevant seeded scenarios before marking a milestone complete. Check reports in
`build/reports/tests`, IDE artifacts in `out/ide-tests`, and per-run backend logs
and databases in `build/ide-backends` when diagnosing failures.

Add the following coverage incrementally; these are planned scenarios, not
claims about tests that already exist:

| Milestone | Seeded IDE acceptance scenario |
|---|---|
| 1. Addresses/tree | Navigate the seeded Index and its page relationship; verify canonical managed identity and physical parent lookup with IDE-process assertions. |
| 2. Lookup/read | Open seeded Index/Page text and properties; check content, type and permissions, then repeat after an IDE restart retaining this test's caches. Extend seeds for other content models. |
| 3. Edit/save | Edit through the editor and invoke Save; independently read backend content and journal state. Inject a concurrent backend edit and verify conflict handling preserves local text. |
| 4. Refresh | Change backend content independently, invoke refresh and verify clean editors update while unsaved editors survive. Cover same-length edits, service recovery and deliberately retained caches. |
| 5. Entry points | Open the same seeded resource through browser and navigation actions; assert one managed file/Document and working associated views. |
| 6. Attachment | Attach/reopen/detach seeded works and check bounded membership. Add a second work to prove unrelated content stays outside the attachment. |
| 7. Find/Replace | Invoke native Find/Replace over attached seeded content, including unopened files; verify matches, backend saves, editor updates and conflict/read-only handling. |

Use Driver for user actions and IDE-process checks for managed IDs, Documents
and PSI. Keep backend verification independent of the editor cache. Extend the
local seed scenarios rather than relying on a developer's database, wiki
credentials or manually prepared notebook state. Restart/recovery tests should
preserve only their own scenario state. Unit/API tests continue to cover smaller
contract cases; notebooks are supplementary diagnostics.

## 1. Define addresses and the managed tree

- [ ] Use `WtManagedAddress` as the single boundary between IDE URLs and backend
  addresses, with wiki title/aspect grammar in `WtPaths`. Avoid protocol stripping
  and authority parsing scattered among callers.
- [ ] Document canonical identities for title directories, slots/aspects,
  synthetic containers and associated binary content. Aspects sharing a backend
  title/page ID still need distinct managed file identities.
- [ ] Define a real hierarchy for traversal. The API jumps from `/` directly to
  `/family/code`; the prototype supplies the intermediate family directory.
  Check intermediate title segments too.

  The seeded IDE identity test exposed missing physical scan-name ancestors in
  flat Page namespaces. The API now resolves these from cached descendant titles
  and lists their immediate children; namespace listings retain their existing
  flat-title presentation. Full managed namespace traversal and `@pages` graph
  handling still need separate coverage.
- [ ] Separate graph navigation from physical children. `Index/.../@pages` lists
  canonical `Page/...` paths, not descendants of the container. Decide its managed
  representation without creating duplicate editable identities. The prototype
  currently rejects such non-hierarchical listings during VFS traversal.
- [x] Choose compatibility for existing URLs: retain managed canonical URLs and
  accept old `wikisource://` URLs as aliases through the common resolver.
- [ ] Keep path conventions changeable, including a possible authority such as
  `wikisource://127.0.100.1:18564/...`. Choose protocol cutover and persisted-URL
  compatibility before migrating callers; this example is not a required scheme.
- [x] Define cache behaviour when an address is attached to a different database.
  Backend switching is a robustness test, not a core workflow; stale content must
  not silently become content from the replacement database.

  Each database has a persistent UUID. Content snapshots retain connection URL,
  UUID and read revision; saves submit the read UUID for server-side validation.
  Replacement at the same URL forces clean-document reload even when timestamps,
  lengths and revision numbers collide. Unsaved text keeps its old identity and
  cannot overwrite the replacement database.

Completion: direct lookup and physical parent/child traversal agree for a small
representative tree; canonical identity and graph-view behaviour are explicit.

## 2. Establish lookup and reading

- [ ] Agree consistent metadata across stat, bulk stat and listings: existence,
  kind, permissions, content model, byte length, timestamp and revision.
- [ ] Verify managed lookup, ID reverse lookup, reads, file types and PSI for
  Index text, Page text, read-only properties and non-wikitext content.
- [ ] Cover spaces, Unicode, escaped leading `@`/`%` and slashes in titles.
- [ ] Reopen after an IDE restart with persistent records already present;
  verify content, metadata and permissions against the current backend.

  The Index-text case is verified by `seededManagedSurvivesIdeRestart`: retain
  project/config/system directories, change the backend while the IDE is closed,
  then check restored content, the same positive managed ID and the Proofread
  Index editor profile. Other content models and permission changes remain pending.
- [x] Keep known managed records valid on transport failure; only successful
  `exists=false` stat results can cause missing-file events. Explicit browser
  refresh preserves cached editors and reloads the tree's connection-error view.
- [ ] Extend unavailable/missing reporting for uncached resources and directory
  traversal interrupted partway through a refresh.
- [ ] Audit threading and network calls: UI rendering and file-type callbacks
  must not unexpectedly perform blocking HTTP. Establish bounded requests,
  background cancellation and useful error reporting.
- [ ] Measure request counts and elapsed time for startup, opening one file and
  refreshing a work. The prototype's attribute callbacks each perform fresh stat
  requests; family checks also list `/`. Separate this amplification from SDK and
  notebook indexing. Design metadata reuse/batching with explicit refresh and
  invalidation rules before scaling up; avoid caching that hides external edits.

Completion: representative resources reliably open and reopen through managed
files without indexing or a project module.

## 3. Establish ordinary editing and saving

- [x] Edit and save through the real editor, independently checking backend text
  and journal/dirty state. Saving remains a local edit; upstream commit is separate.

  Verified by `seededManagedEditorSavesAndReopens` on 2026-10-31 using
  `DISPLAY=:88`: normal typing and Save All for Index text and the guarded Page
  body, independent HTTP content/dirty checks, then close/reopen with matching
  content and the same managed ID. The complete Page comparison preserves header
  and footer markup. The lifecycle scenarios below additionally cover conflicts
  and Index restart. The outage slice below covers failed saves and retry after
  service restart. Undo/redo remains pending.
- [ ] Verify writable text and read-only properties at both file and Document
  levels, including permission changes on cached files.
- [ ] Exercise repeated saves, undo/redo, save-all, close/reopen and IDE restart.
- [x] Preserve the revision associated with the content actually read, including
  content restored from persistent VFS caches after restart. A later stat must
  not silently replace the save's conflict token with a newer revision.
- [x] Retain unsaved edits on conflicts and surface the failure. Verify stale
  saves cannot overwrite newer backend content, then reload and save a new edit.
- [x] Verify unsaved-text retention on connection refusal and successful save
  retry after restarting the service against the same database.
- [x] Exercise delayed stat responses and a timed-out save before handler execution;
  retain unsaved text and retry after clearing the fault.
- [ ] Extend recovery coverage to interrupted/ambiguous writes and other HTTP errors.

Completion: ordinary editor saves work, with regression coverage for conflict
handling and recovery. No Find/Replace action is needed for this milestone.

## 4. Establish refresh and cache invalidation

Implementation notes for lifecycle validation:

- Explicit managed refresh marks the cached file dirty before invoking RefreshQueue.
  Browser Refresh targets open managed files, avoiding a database-wide traversal.
- The content model, connection identity and content's read revision are stored as
  a versioned persistent VFS attribute. Metadata refresh alone cannot advance the
  revision used for saving unsaved text. A real Document reload accepts the newer
  revision. Unknown save revisions fail closed rather than guessing from fresh stat.
- The saved identity includes the API URL and persistent database UUID. VFS API
  reads/stat/listings expose the UUID; content writes carrying an older UUID are
  rejected before journal changes. Changing only the HTTP timeout does not sever
  an editor's valid database binding.
- On build 262, PersistentFS writes its content cache and fires its after-event even
  when the backend stream fails. `WtManagedSaveRecovery` isolates compensation:
  invalidate that content entry and restore unchanged local text's unsaved tracking
  after the event. It uses platform implementation APIs; revalidate on IDE upgrades.
- Managed attribute callbacks preserve known cached attributes when wtbot is
  unavailable, including native SaveAndSync refreshes that bypass browser code.
  Explicit refresh preflights connectivity before starting a native worker.
- The logical managed root is available without HTTP, allowing ManagingFS to
  rehydrate persistent records during offline startup. Asynchronous refresh
  preflights run on pooled threads rather than blocking the EDT.

- [x] Refresh clean open Index Documents after independent same-length backend
  edits through the browser Refresh button, retaining the managed file ID.
- [ ] Extend refresh checks to PSI, other content models and refresh entry points.
- [x] Preserve modified Documents and their original conflict tokens when the
  backend changes underneath them.
- [ ] Verify content, permission, creation and deletion events for supported
  operations. Explicitly document unsupported file operations.
- [x] Exercise service stop/restart against the same database with cached files,
  unsaved Index text, a failed native save and subsequent clean Page refresh.
- [x] Exercise fresh database replacement at the same URL and transport timeouts
  with open documents, deliberately colliding metadata and subsequent recovery.
- [ ] Extend interrupted directory and ambiguous-write coverage.
- [x] Keep refresh bounded: general managed refresh walks existing persistent VFS
  leaves; browser refresh visits open files and expanded graph views. Neither
  enumerates the database through the managed root.

Completion: external changes and service restarts do not leave stale clean
editors, lose local edits or trigger unbounded traversal.

## 5. Migrate plugin entry points to one identity

- [ ] Inventory tree opening, navigation, locator results, properties,
  previews/reference images, actions and restored editor tabs.
- [ ] Route these through the common address/file resolver to managed files;
  remove assumptions that every resource is an old `WtVirtualFile` instance.
- [ ] Check highlighting, PSI, formatting/actions, page navigation and associated
  views on managed files.
- [x] Apply URL compatibility to legacy lookups and persisted Index/properties
  editor tabs, including duplicate legacy/canonical entries. Save canonical URLs
  for subsequent starts and keep one managed editor identity per resource.
- [ ] Extend persisted-state coverage to other content models and project roots;
  account for old raw legacy Documents during a live plugin upgrade.
- [x] Retire legacy browser-file construction and the managed-to-legacy save bridge.
  Graph occurrences are `WikiBrowserNode` values; old URL lookup is a cacheless
  compatibility delegate. Editor files remain managed through `WtWikiFiles`.
- [ ] Remove obsolete filesystem/demo wiring after compatibility is accounted for.

Completion: every supported entry point opens the same managed file/Document
for a resource, with existing plugin workflows preserved.

## 6. Bounded work attachment

Project attachment follows the managed-file cutover. See
[work attachments](../reference/work-attachments.md) for the UI and lifecycle contract.

- [x] Replace the hard-coded Stevenson seed with explicit work selection and
  project-local persistence of attached works.
- [x] Represent an Index and its canonical transcription files as a bounded
  membership set. Only `@wikitext` is attached; properties, scan bytes and other
  aspects remain ordinary browser resources.
- [x] Handle membership changes, unavailable works and detach without scanning
  flat Page, File or Template namespaces across the database.
- [x] Restore membership snapshots from project state, retaining backend/database
  binding and refusing silent rebinding after database replacement.
- [x] Verify attach, canonical editor identity, restart, detach with unsaved text,
  membership refresh and outage recovery in seeded IDE scenarios.
- [ ] Test module-per-Index and managed content roots. Choose the module/root
  representation from that experiment; a project location on disk can store
  configuration without duplicating remote content.
- [ ] Define grouping for File/Template resources when needed, instead of
  implicitly attaching their massive flat namespaces.

Completion: attach, reopen and detach works with predictable membership.
Ordinary file/editor operation remains independent of attachment.

## Deferred: indexing and native Find/Replace

Resume after managed VFS feature parity and an explicit attachment model.

- [ ] Choose project content-root indexing or additional indexable roots from
  the attachment model. Do not index the entire database by default.
- [ ] Verify initial indexing, incremental changes and removal after detach.
  Scope selection must use cached membership and label unavailable scopes clearly.
- [ ] Validate native Find in Files over attached content, including unopened
  files and changes after edits.
- [ ] Then validate Replace in Files in seeded IDE tests: open/closed files,
  saving, conflicts, cancellation and read-only resources. Compare backend text,
  VFS bytes and Documents rather than relying on the results panel alone.
- [ ] Remove static scopes, hard-coded roots and prototype providers once the
  supported implementation replaces them.

Completion: Ctrl+Shift+F and Ctrl+Shift+R work over explicitly attached content
using the established save and refresh lifecycle.

Latest live replacement probe: permissions and all five initial text views agree;
matches appear in the dialog, but Replace All leaves all views unchanged. The
dialog/batch path remains unresolved. Compare the notebook's direct native
replacement method with that path before attributing the failure to saving.

Symbol navigation, tag/template search and backend full-text search are separate
follow-ups. A Search Everywhere provider can query a backend independently;
that alone does not establish native content indexing or replacement support.
SQLite remains an option for later backend search, with a dedicated service deferred.

## Immediate next step

Establish the seeded managed-identity baseline, then migrate existing entry points
incrementally under IDE tests. Track parity explicitly:

- [x] Managed lookup: distinct positive IDs for Index text, Page text and properties;
  `ManagingFS` resolves each ID to the same canonical URL.
- [ ] Browser: site/namespace/title browsing, `@pages` navigation, labels, quality
  and dirty decorations, expansion/selection preservation and error display.
- [x] Opening: default aspect and properties actions open the intended managed
  file; opening through another entry point reuses the same Document.
- [ ] Editing: correct file type and editor/profile, existing formatting actions,
  ordinary save, conflict reporting and read-only properties.
- [ ] Page workflows: previous/next/index navigation, quality actions and associated
  image/preview/annotation views retain their existing behaviour. Extend seeds
  or use controlled service fixtures where these need more than cached text.
- [ ] Lifecycle: targeted refresh, external changes, unsaved edits, restart and
  restored URLs are covered before retiring legacy files and the refresh bridge.

The first integration scenario is `seededManagedFilesHavePersistentIds`. It checks
the registered managed filesystem against the real seeded API without involving
search or additional indexable roots. Browser actions and editor parity require
their own follow-up scenarios; the identity test does not establish full cutover.

Verification on 2026-10-31: the seeded managed-identity IDE scenario and existing
startup/editor/tool-window smoke test passed under Xvfb, as did the Python VFS
suite. Initial runs exposed the missing Page ancestor
contract and a separate platform editor-colour scheme concurrency error; the
isolated rerun passed without suppressing IDE errors.

Browser opening/navigation slice (2026-10-31):

- `WtWikiFiles` is the common resolver for browser Open/double-click, properties
  opening and previous/next page navigation. These entry points now open managed
  files, while the relationship tree continues using its legacy presentation nodes.
- Editor profiles, preview/reference-image requests and OCR/annotation loading use
  shared resource path/metadata accessors rather than requiring `WtVirtualFile`.
  This preserves resource addressing; image/render/OCR service success still needs
  the richer fixtures described above.
- Managed editor tabs retain readable wiki titles. Browser quality actions check
  the managed Document for unsaved edits and refresh it after successful changes.
- `seededBrowserOpensManagedFilesAndNavigatesPages` passed under Xvfb. It exercises
  Index opening and editor profile, read-only properties, Page opening, next/previous
  navigation, browser Open tab reuse, ID reverse lookup and quality-change reload.
- At this slice, browser-node migration and replacement/recovery cases were
  still pending; the later identity/browser slice below supersedes that status.

Lifecycle slice (2026-10-31, `DISPLAY=:88`):

All three lifecycle scenarios passed with the final test workspace fixture;
the VFS/UI unit suites (199 tests) and Python scenario tests (2 tests) also passed.
The fixture starts with the Project pane hidden to avoid the pinned IDE's
colour-scheme startup race, without disabling IDE error reporting.

- `seededManagedRefreshesExternalContent` verifies same-length external Index
  edits become visible in the clean editor through browser Refresh.
- `seededManagedConflictPreservesUnsavedText` keeps local changes through the
  native cache-conflict dialog, verifies Save All reports an edit conflict without
  changing backend text, checks the Document stays unsaved, then explicitly reloads
  and saves a fresh edit successfully.
- `seededManagedSurvivesIdeRestart` reuses the same project, IDE configuration and
  persistent VFS cache across two launches and verifies external changes made
  while the IDE is closed, stable file identity and the restored editor profile.
- Smaller VFS regressions cover persisted read revisions after adapter restart
  and physical content reads while a Document remains unsaved. Test-only revision
  injection is confined to the managed integration server.

Outage and URL compatibility slice (2026-11-01):

- `seededManagedRecoversFromBackendOutage` stops the owned HTTP server, exercises
  browser and native save refreshes, verifies a rejected save retains unsaved
  text, restarts wtbot with the same SQLite database, retries saving and refreshes
  an independently changed clean Page. Managed IDs remain stable.
- `seededLegacyUrlsRestoreAsManagedFiles` starts from persisted legacy Index and
  properties URLs plus a duplicate canonical Index entry. It verifies two managed
  tabs, read-only properties, a native save and canonical URLs written on close.
  Its next launch exercises those persistent editor records with wtbot stopped.
- The test server's explicit `--resume` mode preserves only this scenario's data;
  production serving behavior is unchanged. The VFS unit regression also invokes
  native refresh directly while unavailable and checks the shared Document and ID.

Verification on 2026-11-01 (`DISPLAY=:88`): startup smoke, browser/navigation,
conflict recovery, service outage/retry, and legacy URL migration/offline editor
restoration all passed. VFS/UI unit suites (200 tests) and Python scenario tests
(2 tests) also passed. The offline case explicitly checks the Proofread Index
editor profile before wtbot is restarted.

Database identity, timeout and browser retirement slice (2026-11-01):

- `DatabaseIdentity` is a singleton persisted by migration `a71b9d42e608`.
  A service restart preserves it; independently created databases receive different
  UUIDs. API identity validation uses the write's database Session before invoking
  the VFS writer. Identity-less legacy clients remain compatible; managed editors
  require an identity and fail closed until content has been read from an updated API.
- `seededManagedRejectsReplacementDatabase` replaces the owned service's database
  twice at the same address. Clean text refreshes with unchanged revid/length/time;
  unsaved text cannot save into the next database, then explicit reload accepts its
  identity and saving works. Platform file IDs remain assigned by ManagingFS.
  Explicit reopening also revalidates the binding without requiring browser Refresh.
- `seededManagedRecoversFromRequestTimeout` uses a one-second client timeout and
  a test-only pre-handler stall. Delayed stat and save responses preserve the editor;
  clearing the fault permits retry. The stalled write never reaches the domain
  handler. This does not establish the outcome of a real timeout after a commit.
- Browser graph nodes are keyed by database, parent occurrence and canonical path.
  `@pages` links do not create duplicate editable files or mutate a shared file's
  parent. Metadata reload, quality actions, opening and previous/next navigation
  use the same managed files. Backend switching includes managed unsaved documents;
  failed saves cannot approve a switch, and discard is explicit.
- The legacy URL filesystem owns no records or refresh traversal. General managed
  refresh iterates existing DB-backed VFS children, not API relationship listings.
  Unit checks cover this bound, graph-parent identity and endpoint rebind with
  identical metadata.

A database copy preserves its UUID and is treated as the same lineage. An
independent fork must receive a new UUID while its service is stopped. The tests
replace databases between service processes; replacing an active SQLite file
under pooled connections is outside this contract.

Verification on 2026-11-01: eight distinct IDE scenarios passed on `DISPLAY=:88`
(startup, browser/navigation, ordinary save/reopen, offline legacy restoration,
database replacement, timeout recovery, service outage/restart and revision conflict).
The VFS/UI suites passed 204 tests, and 90 Python API/scenario/migration tests passed.
The replacement case deliberately collides revision, timestamp and length; the
bounded-refresh regression asserts that no backend directory listing occurs.

Search and replace remains deferred until work attachment and indexing are explicit.
