# Managed Wikisource VFS migration

Status: prototype in progress, 2026-10-30.

Migrate ordinary Wikisource browsing, opening, editing and saving to platform-managed
virtual files. Establish those behaviours before enabling indexing and cross-work
Find/Replace as supported features. Each numbered step is a separate milestone;
its completion checks are the gate for moving on.

The search experiment establishes feasibility. Keep it available for diagnosis,
but do not expand it while the basic file lifecycle is being established.

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
- Old and managed files currently have separate Documents. A targeted refresh
  bridge updates clean legacy editors after managed saves; this is temporary,
  incomplete compatibility infrastructure.

Diagnostics: [replacement notebook](../notebooks/managed-replace.ipynb),
`WtManagedReplaceProbe`, `WtManagedBackendFileSystemTest`, `WtManagedWorkTest`.
Passing fixture tests do not replace verification through the running plugin.

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
- [ ] Separate graph navigation from physical children. `Index/.../@pages` lists
  canonical `Page/...` paths, not descendants of the container. Decide its managed
  representation without creating duplicate editable identities. The prototype
  currently rejects such non-hierarchical listings during VFS traversal.
- [ ] Keep path conventions changeable, including a possible authority such as
  `wikisource://127.0.100.1:18564/...`. Choose protocol cutover and persisted-URL
  compatibility before migrating callers; this example is not a required scheme.
- [ ] Define cache behaviour when an address is attached to a different database.
  Backend switching is a robustness test, not a core workflow; stale content must
  not silently become content from the replacement database.

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
- [ ] Distinguish authoritative missing files from temporary backend failures.
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

- [ ] Edit and save through the real editor, independently checking backend text
  and journal/dirty state. Saving remains a local edit; upstream commit is separate.
- [ ] Verify writable text and read-only properties at both file and Document
  levels, including permission changes on cached files.
- [ ] Exercise repeated saves, undo/redo, save-all, close/reopen and IDE restart.
- [ ] Preserve the revision associated with the content actually read, including
  content restored from persistent VFS caches after restart. A later stat must
  not silently replace the save's conflict token with a newer revision.
- [ ] Retain unsaved edits on conflicts and backend failures, and surface the
  failure. Verify stale saves cannot overwrite newer backend content.

Completion: ordinary editor saves work, with regression coverage for conflict
handling and recovery. No Find/Replace action is needed for this milestone.

## 4. Establish refresh and cache invalidation

- [ ] Refresh clean open Documents after independent backend edits, including
  same-length edits; verify VFS bytes, Documents and PSI converge.
- [ ] Preserve modified Documents and their original conflict tokens when the
  backend changes underneath them.
- [ ] Verify content, permission, creation and deletion events for supported
  operations. Explicitly document unsupported file operations.
- [ ] Exercise service restart, outage/recovery and database replacement with
  cached metadata and persistent content already present.
- [ ] Keep refresh bounded; refreshing one work must not enumerate the database.

Completion: external changes and service restarts do not leave stale clean
editors, lose local edits or trigger unbounded traversal.

## 5. Migrate plugin entry points to one identity

- [ ] Inventory tree opening, navigation, locator results, properties,
  previews/reference images, actions and restored editor tabs.
- [ ] Route these through the common address/file resolver to managed files;
  remove assumptions that every resource is an old `WtVirtualFile` instance.
- [ ] Check highlighting, PSI, formatting/actions, page navigation and associated
  views on managed files.
- [ ] Apply the agreed compatibility policy to existing `wikisource://` URLs and
  persisted editor/project state.
- [ ] Retire the duplicate editable identity and temporary legacy refresh bridge
  once entry points converge. The current bridge is not two-way coherence.
- [ ] Remove obsolete filesystem/demo wiring after compatibility is accounted for.

Completion: every supported entry point opens the same managed file/Document
for a resource, with existing plugin workflows preserved.

## 6. Add bounded work attachment

- [ ] Replace the hard-coded Stevenson seed with explicit work selection and
  project-local persistence of attached works.
- [ ] Represent an Index and its canonical transcription files as a bounded
  membership set; include other aspects deliberately.
- [ ] Handle membership changes, unavailable works and detach without scanning
  flat Page, File or Template namespaces across the database.
- [ ] Test module-per-Index and managed content roots. Choose the module/root
  representation from that experiment; a project location on disk can store
  configuration without duplicating remote content.
- [ ] Define grouping for File/Template resources when needed, instead of
  implicitly attaching their massive flat namespaces.

Completion: attach, reopen and detach works with predictable membership.
Ordinary file/editor operation remains independent of attachment.

## 7. Add indexing, then native Find/Replace

- [ ] Choose project content-root indexing or additional indexable roots from
  the attachment model. Do not index the entire database by default.
- [ ] Verify initial indexing, incremental changes and removal after detach.
  Scope selection must use cached membership and label unavailable scopes clearly.
- [ ] Validate native Find in Files over attached content, including unopened
  files and changes after edits.
- [ ] Then validate Replace in Files using the notebook: open/closed files,
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

Start with milestone 1: settle and test the canonical tree/address contract,
particularly intermediate directories and `@pages`. Retain the search probes as
diagnostics while working through lookup, ordinary saves and refresh in order.
