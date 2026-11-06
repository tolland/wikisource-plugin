# Project work attachments

In the Wikisource **Browser**, select an Index or a proofread Page and choose
**Attach Work**. A Page resolves to its owning Index. The **Attached works**
branch shows the Index and its last confirmed text membership. Expand the work
to open **Index text** or a canonical **Page …** file. Opening a member uses the
same managed file ID and editor document as ordinary browser navigation.

An attachment contains the Index's `@wikitext` and the available transcription
files returned by that Index's `@pages` relationship view. It does not attach
the entire Page namespace, follow nested subpages recursively, or include
properties, scan bytes, stylesheets, File or Template namespaces. Those resources
remain available through ordinary browsing. Attachment does not create modules
or content roots. The initial indexing integration contributes eligible text files
as additional project index roots and supplies a `Wikisource: <work>` search scope.

To search it, open **Find in Files** (`Ctrl+Shift+F`), select **Scope**, then choose
**Wikisource: <work>**. **Project Files** uses IntelliJ content roots and does not
include these additional files. Search Everywhere is a different search surface.
The scope provider is registered through `com.intellij.searchScopesProvider`.

Indexing happens inside IntelliJ. The API sees metadata requests for selection
and content reads when IntelliJ needs bytes; already-cached content and up-to-date
indexes can avoid new `/vfs/content` requests. A lack of content requests alone
does not mean indexing failed.

Index eligibility is determined from metadata: a file must have a real revision
(`placeholder=false`) or a saved local edit (`dirty=true`). Untouched scaffold and
prepopulated OCR defaults are excluded, even when they contain substantial text.
Saved local transcriptions remain eligible while awaiting their first upstream
commit. Explicitly accepting and saving a default also makes it eligible; no text
comparison is used to guess whether it has been reviewed. Index text is included;
properties and unrelated titles are excluded.

Selection uses bulk stat before resolving managed files. It neither opens default
bodies nor writes, saves or accepts them. Merely opening a default page does not
make it eligible. Attachment changes, managed content events and explicit work
refresh update the cached roots. Index/scope callbacks return cached snapshots
without HTTP; project reopen revalidates eligibility in the background. An
unavailable work contributes no files until its metadata can be verified.

These are file-level scopes over serialized wikitext. They do not enforce the
proofread editor's guarded regions during native Replace in Files. A transcription-
body-only replacement command remains separate work.

Select an attached work or one of its members and choose **Refresh Work** to
replace its membership with a fresh snapshot. Removed members leave the
snapshot; existing editor tabs remain open. Discovery lists only that Index's
`@pages` and batches metadata for its text files. It does not read every member's
content or enumerate namespaces.

Project state is saved in `.idea/wikisource-works.xml`, including canonical
addresses, connection identity, database UUID and the last confirmed membership.
Project reopen restores that snapshot without rediscovering work membership.
**Refresh Work** checks it explicitly. Failed discovery leaves the snapshot
intact. A different connection or replacement database cannot silently replace
an existing attachment: detach it and attach the intended work explicitly.
Opening an attached member validates the current backend binding; already-open
managed editors retain their existing offline caching and save guards.

**Detach Work** removes only the project association. It does not delete backend
content or managed VFS records, close editors, or save/discard unsaved text.
Detaching the last work may cause IntelliJ to remove the now-empty settings file.
Reattaching the same Index (including through one of its Pages) updates the
existing association rather than creating a duplicate.

`WtManagedAddress` remains the address boundary, `discoverManagedWork` discovers
bounded membership, and the project service `WtWorkAttachments` owns persistence
and lifecycle operations. The tree is a view over that state, not an alternate
filesystem. `indexableWorkContent` selects persisted content, and the project
service `WtAttachedWorkIndex` resolves eligible managed leaves in the background.
Its contributor and scope provider share those snapshots. The earlier static
demos and replacement probes remain removed.

The seeded IDE scenarios `seededWorkAttachmentPersistsAndDetaches` and
`seededWorkMembershipRefreshAndRecovery` exercise these flows; see
[IDE integration tests](ide-integration-tests.md) for execution and artifacts.
`attachedWorkIndexSkipsUnreviewedDefaults` checks native content indexing against a
partially transcribed work and eligibility after an explicit save. It also opens
the actual Find in Files popup, selects the contributed scope and checks matches
for unopened remote pages and local transcriptions, excluding unreviewed defaults.

Initial integration verification: 118 VFS and 90 UI tests, 11 backend fixture/
placeholder tests, the native-index scenario and the three-launch attachment
persistence/detach scenario passed. No content read was made for the untouched
scaffold page in the indexing scenario.
