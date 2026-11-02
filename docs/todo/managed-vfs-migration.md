# Managed Wikisource VFS migration

Status: **core migration complete** for the supported Index/Page workflow.
Bounded work attachment is also implemented. Performance and the small parity
check below are non-blocking follow-ups; indexing and Find/Replace are separate
feature work.

## Completed baseline

- [x] One registered filesystem, `wikisource-wtbot`, with platform-owned positive
  `VirtualFileWithId` identities and working reverse lookup through `ManagingFS`.
- [x] Common managed-file resolution through `WtWikiFiles` and address construction
  through `WtManagedAddress`; browser relationship nodes remain separate from files.
- [x] Browser opening, properties, page navigation and quality actions use managed
  files and reuse existing editor identity. Index/Page editor profiles are retained.
- [x] Ordinary Index/Page editing and saving, read-only properties, close/reopen,
  external refresh and persistent editor restoration, including offline startup.
- [x] Unsaved text and its read revision survive conflicts, outages and failed
  saves. Database UUID checks prevent stale writes after database replacement.
  Deterministic timeout/retry and recovery scenarios are covered.
- [x] Refresh stays bounded to known managed files and browser views rather than
  traversing the database root.
- [x] Project-local work attachment, canonical Index/Page text membership,
  membership refresh, project reopen and detach without discarding editor changes.
- [x] Remove raw legacy files, the old-URL adapter, demo filesystem and obsolete
  search/replace prototypes, notebook and dependency.

Only managed URLs are supported. Resources referenced by old `wikisource://`
URLs must be reopened from the browser. Managed filesystem create, copy, move,
rename and delete operations are unsupported; implementing them is separate work.

## Non-blocking follow-ups

- [ ] **Measure request amplification and UI responsiveness.** Record request counts
  and elapsed time for startup, opening one file and refreshing a representative
  work. Attribute callbacks currently issue backend stat requests, and family
  checks list `/`. Check which calls occur on the UI thread. Fix observed blocking
  or excessive requests with explicit invalidation rules that preserve freshness.
- [ ] **Run a small everyday-workflow parity check.** Check undo/redo, formatting
  actions, locator opening and preview/reference-image workflows with the required
  services configured. Record the outcome and add targeted regression coverage for
  failures. Broader content-model and PSI test matrices can grow as needed.

These follow-ups do not reopen the completed migration. Track any concrete
regression found during them as a specific bug.

## Separate feature and reliability work

- **Indexing and native Find/Replace:** choose bounded indexable roots from attached
  membership; verify initial/incremental indexing and removal after detach, then
  Find and Replace behavior for unopened files, read-only content and save failures.
- **Module per Index/content roots:** an experiment for the indexing feature, not
  a requirement for ordinary managed files or attachment.
- **Other resource grouping and search:** File/Template views, symbol navigation,
  tag/template search and backend full-text search when their use cases are needed.
- **Additional hardening:** interrupted directory refresh, ambiguous writes after
  a possible server commit, other HTTP errors, more content models and path cases.
  Existing timeout tests cover failure before the write handler executes.
- **Future address conventions:** retain the common address boundary; implement an
  authority or path-format change only when required.
- **IDE upgrades:** revalidate `WtManagedSaveRecovery`, which compensates for failed
  saves using platform implementation APIs on the pinned build 262.

## Evidence and reference material

Seeded IDE scenarios cover managed identity, browser/navigation, ordinary saving,
external refresh, conflicts, restart/offline restoration, outage recovery, database
replacement, timeouts and work-attachment lifecycle. The user also manually
verified opening, editing, saving and refreshing.

Latest managed-only cleanup verification: **114 VFS + 90 UI unit tests passed**;
browser/navigation and two-launch managed offline restoration passed on
`DISPLAY=:88`, including checks that both retired protocols are unregistered.
The built plugin contains one Wikisource filesystem registration and no retired
file, alias, demo or search-prototype classes.

See [VFS paths and identity](../reference/vfs-paths.md),
[work attachments](../reference/work-attachments.md) and
[IDE integration tests](../reference/ide-integration-tests.md) for implementation
contracts, usage, test commands and artifacts.
