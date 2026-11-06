# Wikisource browser

The Wikisource tool window (anchored on the right; its stripe button is
currently titled **My Tool Window**) has two tabs: **Browser** and **Debug**.
The Debug tab is described in [Connecting to wtbot](connecting.md). The
browser shows what the configured wtbot has cached; it does not fetch from the
wiki itself. Fetching new works into wtbot is done with wtbot's own tools (see
the wtbot repository, `../wtbot`).

## The tree

```
Wikisource
├── Attached works            (works attached to this project, see below)
└── wikisource/en            (one node per registered site: family/code)
    ├── (Main)
    ├── Index
    │   └── Some book.djvu
    │       └── Pages         (the Page: titles this Index paginates)
    │           ├── Some book.djvu/1
    │           └── …
    └── Template, Author, …
```

- A **title** is a node that can both be opened and contain subpages
  (`Book/Chapter 1`). The `Page` namespace is not listed under the site — there
  is one title per scan — so pages are reached through their Index's
  **Pages** node.
- **Double-click** a title to open its text in an editor. Opening the same
  title again, from anywhere, reuses the existing editor tab.
- Names in **blue with a star** have local edits saved in wtbot but not yet
  committed to the wiki. Names in **grey italics** are placeholders: the page
  does not exist on the wiki yet and has no local edits.
- A coloured **●** after a Page shows its proofreading quality, in the usual
  ProofreadPage colours.
- Selecting a node shows its properties (path, kind, revision, content model,
  …) in the pane below the tree.

### Context menu

| Item | Does |
|---|---|
| Open | Opens the title's text (same as double-click). |
| Show Properties | Opens the title's read-only JSON properties in an editor. |
| Set Page Quality… | Sets the ProofreadPage quality level on every selected Page. |
| Mark Ready to Validate | Sets selected Pages to level 3 (Proofread). |
| Copy Path | Copies the node's backend path. |
| Refresh | Re-reads the node from wtbot. |

Quality changes are ordinary saves: each page is read, its `<pagequality>` tag
rewritten and saved, so it becomes a local edit awaiting commit. Pages with
unsaved changes in an open editor, and pages that changed on the backend in
the meantime, are skipped and reported.

The **Refresh** button above the tree re-reads every open Wikisource editor
from wtbot and reloads the tree, keeping expansion and selection. Clean
editors pick up newer text; unsaved text is kept.

Saving in an editor stores the text in wtbot's local edit journal. Nothing is
sent to the wiki until it is committed, which is currently done outside the
IDE (with wtbot's tools or its viewer).

## Attached works

Attaching a work makes its transcriptions part of the project for searching.

1. Select an Index, or any proofread Page of it, and click **Attach Work**.
   A Page resolves to its owning Index.
2. The work appears under **Attached works**. Expand it to open **Index text**
   or any **Page …** member; these are the same editors as ordinary browsing.
3. Search it with **Find in Files** (`Ctrl+Shift+F`): set **Scope** to
   **Wikisource: <work>**. The **Project Files** scope does not include it.

A work contains the Index text and the Page texts listed by the Index's
**Pages**. It does not include properties, scans, stylesheets, or the File and
Template namespaces, and it does not add modules or content roots.

Only pages with real content are indexed: a page is included when it has a
revision on the wiki or a saved local edit. Untouched placeholders — including
pages pre-filled with unreviewed OCR text — are left out until you edit and save
them. Opening a placeholder does not make it eligible.

- **Refresh Work** re-reads the Index's page list and replaces the membership
  snapshot. Removed pages leave the work; their open editors stay open. If the
  refresh fails, the last snapshot is kept.
- **Detach Work** removes only the project association. Backend content, open
  editors and unsaved text are untouched.
- Attaching the same Index again (directly or through one of its Pages)
  updates the existing attachment rather than adding a duplicate.

Attachments are stored in `.idea/wikisource-works.xml` with the backend address
and database identity they were made against. Reopening the project restores
them without contacting wtbot; eligibility is rechecked in the background. If
you switch to a different backend or database, the attachment is not silently
rebound: detach it and attach the work again.

Find in Files over an attached work searches and replaces whole page text,
including the `<noinclude>` header and footer of Page bodies; the proofread
editor's protected regions do not apply there.
