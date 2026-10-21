# The `wikisource://` tree: paths, nodes and aspects

How the VFS names things today. Code: `src-py/wtbot/vfs/` (`paths.py`,
`namespaces.py`, `nodes.py`, `aspects.py`, `wikisource.py`); client side
`wikitext-vfs/.../vfs/WtPaths.kt` and the tool window's `WikisourceTreeStructure`.

## Grammar

```
/{family}/{code}/{namespace}/{title segments...}[/@{aspect}]
```

| Path | Is |
|---|---|
| `/` | root: the registered sites |
| `/{f}/{c}` | a site: the namespaces that hold cached titles (`Page` is unlisted, see below) |
| `/{f}/{c}/Book` | a namespace container; `(Main)` is the main namespace |
| `/{f}/{c}/Book/Virtues and vices` | a **title node** — a directory |
| `…/Virtues and vices/Chapter 1` | a subpage: another title node |
| `…/Virtues and vices/@wikitext` | an **aspect file**: the content you edit |
| `…/Virtues and vices/@props` | an aspect file: read-only JSON properties |
| `/{f}/{c}/Index/Foo.pdf/@pages` | an aspect container: the `Page:` titles the Index paginates |

Only the **last** segment can be an aspect, and only after at least one title
segment. A title segment that itself starts with `@` or `%` is escaped (`%40`,
`%25`), so a trailing `@name` is never ambiguous.

## Why a title is a directory

A wiki title is often a page *and* a container of subpages (`Book:X`,
`Book:X/Chapter 1`), and can offer more than one view of itself (content,
properties, later revisions, scan…). The IntelliJ VFS has no node that is both
file and directory, and flipping a path from file to directory when its first
subpage is fetched would break every open editor on it. So the title is always
a directory; the things you open are its `@aspect` files, at paths that never
change.

The tool window follows the DataGrip Database Explorer model: it shows titles
(and `@pages`), not aspect files. Double-click opens the node's default aspect
(`aspects[0]`, normally `@wikitext`); a branch expands by its handle. Other
aspects are reached from the context menu ("Show Properties").

`read`/`write` act on aspect files only; a bare title path is a directory
(`NotAFile` / a write error). Endpoints that only ask *which page* a path means
(`/pages/nav`, `/pages/resolve`, OCR, annotations, locator-index, preview,
reference image) accept either the title node or any of its aspects.

## Namespaces and subpages

A title splits into `(namespace, rest)` against the site's `Namespace` table
(siteinfo), never by the colon alone — `Faust: Part One` is a mainspace title.
A site with no siteinfo yet falls back to the standard MediaWiki and
ProofreadPage names; an unknown prefix then resolves as mainspace, which still
works because the full title is what is looked up.

The namespace's `subpages` flag decides what a slash means:

- `subpages = true` — `Book:A/B/C` is `C` under `B` under `A`. When no title
  holds `A/B`, it is a **synthetic node** (a container with no page of its own,
  no aspects, no `stable_id`).
- `subpages = false` (`Page`, `File`) — the slash belongs to the title, so
  `Page:Foo.djvu/171` is `/Page/Foo.djvu/171`, one node.

`Page` is not listed under the site (one title per scanned page); it stays
addressable by path and listable directly. Pages are browsed through their
Index's `@pages`.

## Wire shape

`Node` / `Stat` gained `has_children` (a directory with something to expand)
and `aspects` (names a title node offers, default first; empty for files and
synthetic nodes). Each aspect is a child of the node at `{path}/@{aspect}`.
Title nodes are listed with `kind: directory`; their `length` is `None` and
`writable` false — the aspect file carries the revid, length and `writable`
that saves depend on, so open the aspect file, never mint one from node
metadata.

## Not built yet

- **Context-action extension point.** The tool window's popup is a fixed group
  today. The intent is an action group (`Wikisource.NodeContextMenu`) whose
  actions receive the selected node (site, namespace, title, content model,
  aspects, `dirty`) through a `DataKey` and decide their own visibility in
  `update()` — e.g. "Show in MediaWiki", and the commit workflow (review/approve
  a dirty page against `GET /commit/pending`, push via `POST /commit/{page_pk}`,
  discard via `DELETE /commit/{page_pk}/pending`) that the viewer's `/commits`
  page does out of band.
- **Editable properties.** `@props` is a read-only JSON view of state other
  operations own (fetch, commit, journal).
- **Creating a subpage** from the tree (a `Missing` path).
