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
remain available through ordinary browsing. Attachment does not create modules,
register content roots or enable indexing and Find/Replace.

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
filesystem. Future search/indexing integrations will use the attachment model;
the earlier demo and search/replace scaffolding has been removed.

The seeded IDE scenarios `seededWorkAttachmentPersistsAndDetaches` and
`seededWorkMembershipRefreshAndRecovery` exercise these flows; see
[IDE integration tests](ide-integration-tests.md) for execution and artifacts.
