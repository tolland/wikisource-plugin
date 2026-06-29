# wtbot — Python backend design

Status: **draft / proposal**. This document describes the operations the Python
backend (`wtbot`) needs to support so the IntelliJ plugin can treat a remote
Wikisource as an editable, locally-cached filesystem. It is the thing to agree on
*before* we settle the schema and write the endpoints. Schema DDL and SQLModel
shapes shown here are proposals, not yet the live code.

---

## 1. Mental model: git, not Samba

The plugin does **not** talk to MediaWiki live, and the cache is **not** a
transparent network filesystem. The model is explicit, git-style:

```
  fetch  (cache-fill)   remote wiki  ──pywikibot──▶  local SQLite cache
  edit   (VFS write)    IDE buffer   ──────────────▶ local journal
  commit (push back)    journal      ──pywikibot──▶  remote wiki
```

Three verbs, three lifecycles, deliberately decoupled:

1. **fetch / cache-fill** — "check out" a work from the wiki into the cache.
   Out-of-band, like `git fetch`/`git checkout`. Triggered by an explicit
   request, *not* by the VFS. Slow, batched, runs pywikibot.
2. **edit** — the IDE reads/writes/lists against the cache through the VFS.
   Fast, local, never touches the network.
3. **commit** — pushed-back edits, queued as a journal and written to the wiki
   by pywikibot, with edit-conflict detection. Also explicit, like `git push`.

Because fetch and commit are explicit, round-trip latency to the wiki is never on
the IDE's hot path. The cache is the source of truth for the editor; the wiki is
the source of truth for the world.

---

## 2. Two interface surfaces

The plugin reaches the backend through exactly two distinct surfaces. Keeping
them separate is a design constraint, not an accident — they have different
performance profiles, different consistency needs, and different triggers.

### A. VFS surface (read / write / list / move)
Backs `WtVirtualFileSystem` (`wikisource://`). Synchronous, low-latency,
cache-only. Operations:

| Op       | Meaning                                                       |
|----------|--------------------------------------------------------------|
| `list`   | children of a node (Index → its Pages; site → its Indexes)   |
| `read`   | body + metadata of one page (the wikitext shown in the editor)|
| `write`  | save editor buffer → appends to the **journal**, marks dirty |
| `stat`   | timestamp / size / dirty flag (drives `VirtualFile` polling) |
| `move`   | rename a title (local-only until committed)                  |
| `copy`   | duplicate a node                                              |
| `delete` | tombstone a node locally                                      |

A `write` never goes to the wiki. It records a local revision in the journal and
flips `dirty=1`. This is the key invariant: **saving in the IDE is cheap and
offline**; pushing to the wiki is a separate, explicit `commit`.

### B. Cache-fill surface (fetch requests)
Out-of-band job queue. Asynchronous. The plugin submits a request and polls
progress; pywikibot does the slow work and fans out child requests as it
discovers structure. This is the "git checkout" path and is **never** invoked
implicitly by the VFS.

Request identity follows **pywikibot conventions** (this matches the existing
`Site` model: `family` + `code` + `articlepath`):

```
title:  Index:Wittgenstein_-_Tractatus_Logico-Philosophicus,_1922.djvu
family: mywikisource
code:   en
depth:  implied        # how aggressively to expand associated assets
```

---

## 3. Content model: ProofreadPage and implied assets

Wikisource is not flat. Certain titles imply a structured set of other objects,
and the backend must understand this to fetch a *work*, not just a *page*.

### Namespaces we care about

| Namespace      | ns id | Treatment                                              |
|----------------|-------|-------------------------------------------------------|
| `Index:`       | 106   | ProofreadPage index — root of a scanned work          |
| `Page:`        | 104   | one scanned page's transcription (`Title.djvu/N`)      |
| `File:`        | 6     | the backing DjVu/PDF — **stored as a file, not a row** |
| main (article) | 0     | the composed work that transcludes Pages              |
| `Book:` etc.   | site  | collection/landing pages                              |

### Implied-asset expansion

Given a fetch request for an `Index:`, the backend expands it into the full work.
`Index:Foo.djvu` implies:

1. **`File:Foo.djvu`** — the scan. Persisted to disk (see §5), referenced from
   the cache by path, not inlined as a SQLite blob.
2. **`Page:Foo.djvu/1 … Page:Foo.djvu/N`** — one per scan page, where `N` comes
   from the Index `<pagelist>` / the file's page count.
3. *(future)* **transcluded templates and other assets** referenced by the Index
   or its Pages.

`depth` on the request controls how far expansion goes:

| `depth`        | expands to                                                |
|----------------|-----------------------------------------------------------|
| `single`       | just the requested title, no expansion                    |
| `index`        | Index + its File + all its Pages (the common case)        |
| `transclusion` | also the mainspace work(s) that transclude those Pages    |
| `implied`      | (alias for the "do the sensible thing for this ns") policy|

Expansion is recorded as a **parent → child** fan-out of fetch requests so the
plugin can watch aggregate progress on the one request it submitted.

---

## 4. Operations catalog

### 4.1 Cache-fill API (async, surface B)

```
POST /fetch
  body: { title, family, code, depth }
  → 202 { request_id, status: "pending" }

GET  /fetch/{request_id}
  → { request_id, status, progress_done, progress_total,
      children: [ {request_id, target_title, status}, ... ],
      error_message? }

GET  /fetch?status=pending|in_progress|...      # queue inspection / CLI
POST /fetch/{request_id}/cancel
```

Lifecycle of a request: `pending → in_progress → done | error | cancelled`.
A worker (pywikibot) claims `pending` rows, fans out children for `Index:`
requests, updates `progress_*`, writes resulting bodies into `pages`, and writes
`File:` payloads to disk.

### 4.2 VFS API (sync, surface A)

```
GET    /vfs/{family}/{code}/{title}          # read body + metadata
GET    /vfs/{family}/{code}/{title}?list=1   # list children
HEAD   /vfs/{family}/{code}/{title}          # stat (timestamp, dirty)
PUT    /vfs/{family}/{code}/{title}          # write → journal, dirty=1
POST   /vfs/move    { from, to }
POST   /vfs/copy    { from, to }
DELETE /vfs/{family}/{code}/{title}
```

### 4.3 Commit API (async, push-back)

```
POST /commit/{title}      # enqueue dirty body → wiki, captures base_revid
  → { commit_id, status: "pending" }
GET  /commit/{commit_id}  # → success | conflict | error (+ result_revid)
GET  /commits?status=pending
```

A commit carries `base_revid` (the revid the edit was based on) as the conflict
token. If the remote has moved on, the commit lands as `conflict`, not silently
lost — the plugin can surface "save failed, here's why" after the fact.

---

## 5. File handling (the `File:` exception)

Everything except `File:` lives as text in SQLite. `File:` objects (DjVu/PDF
scans, images) are **persisted to disk** and referenced by path:

```
cache/
  blobs/
    {family}/{code}/{sha1[:2]}/{sha1}        # content-addressed scan files
```

The `pages` row for an `Index:` carries `file_ref` pointing at the on-disk blob,
plus `page_count`. Rationale: scans are large and binary; SQLite is the wrong
home for them, and content-addressing makes re-fetch idempotent and dedupes
across works that share a scan.

---

## 6. Data model

### 6.1 Reconcile the two existing schemas

There are currently two divergent definitions and they must converge:

- **`schema/schema.sql`** — rich, WAL-IPC-aware: `sites, pages, transclusions,
  fetch_requests, commits`, FTS5 over bodies. Keyed on `host` / `api_url`.
- **`sqlmodel/`** — minimal: `Site(family, code, articlepath)`, `Page`,
  `Revision`, `Namespace`. Keyed on pywikibot `family` / `code`.

**Proposal:** keep `schema.sql` as the architectural target (it already models
the journal and the queue) but adopt the **pywikibot `family`/`code` site
identity** from the SQLModel side as canonical, since that is the request
vocabulary (`title:x family:y code:z`) and what pywikibot itself uses.
`host` / `api_url` become derived/optional columns on `sites`, not the key.

> Also note: `wtbot/main.py` imports `wtbot.model.sqlmodel` but the package is
> `wtbot.sqlmodel` — stale import, currently broken. To be fixed when we wire the
> real app.

### 6.2 New table — cache-fill requests (the explicit ask)

This is the table §2.B needs. It is essentially `schema.sql`'s `fetch_requests`,
restated in pywikibot vocabulary and given an explicit `depth` policy. Proposed
SQLModel:

```python
# wtbot/sqlmodel/fetch_request.py  (proposed)
from datetime import datetime
from enum import Enum
from sqlmodel import SQLModel, Field


class FetchKind(str, Enum):
    single = "single"            # just this title
    index = "index"              # Index + File + Pages
    transclusion = "transclusion"  # + mainspace works transcluding those Pages
    page = "page"                # a single Page: (usually a fan-out child)


class FetchStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    done = "done"
    error = "error"
    cancelled = "cancelled"


class FetchRequest(SQLModel, table=True):
    pk: int | None = Field(default=None, primary_key=True)

    site_pk: int = Field(foreign_key="site.pk")
    parent_pk: int | None = Field(default=None, foreign_key="fetchrequest.pk")

    # pywikibot-style target identity
    title: str                              # 'Index:...djvu', 'Page:...djvu/3', ...
    kind: FetchKind = FetchKind.index
    depth: int = 0                          # 0 = this title only; >0 = expand assets

    status: FetchStatus = FetchStatus.pending
    priority: int = 0                       # higher = sooner ("open this now" jumps queue)
    progress_done: int = 0
    progress_total: int | None = None
    error_message: str | None = None

    requested_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

`parent_pk` gives the Index→Pages fan-out; the plugin polls the parent and reads
aggregate `progress_done / progress_total`.

### 6.3 The journal (separating saves from cached remote state)

Each IDE save must be kept distinct from the last-fetched remote revision — a
local transaction log, not an in-place overwrite of the cached body. This serves
two needs at once: undo/history of local edits, and the queue of changes to push
back via pywikibot.

`schema.sql` already has the *outbound* half (`commits`: one row per push
attempt, with `base_revid` as conflict token, kept as a log so rejected edits are
visible/retriable). The missing piece on the SQLModel side is an `EditJournal`
that records every local save before it is ever committed:

```python
# wtbot/sqlmodel/edit_journal.py  (proposed)
class EditJournal(SQLModel, table=True):
    pk: int | None = Field(default=None, primary_key=True)
    page_pk: int = Field(foreign_key="page.pk")
    base_revid: int | None = None        # remote revid this edit started from
    body: str                            # the saved buffer
    comment: str | None = None           # edit summary (filled at commit time)
    saved_at: datetime = Field(default_factory=datetime.utcnow)
    committed: bool = False               # has this been pushed back yet?
```

Flow: VFS `write` → append `EditJournal` row + set `pages.dirty=1`. `commit` →
read latest uncommitted journal rows, create `commits` rows, pywikibot pushes,
mark `committed=True` on success.

---

## 7. The fetch worker (pywikibot side)

A loop, not yet implemented, that drives surface B:

```
1. claim a pending FetchRequest (BEGIN IMMEDIATE, highest priority first)
2. resolve Site via pywikibot (family, code, articlepath)
3. dispatch on kind:
     single  → fetch one page, upsert into `pages`
     index   → fetch Index; read <pagelist>/page_count;
               download File: to cache/blobs/...; set file_ref, page_count;
               fan out N child `page` requests (parent_pk = this)
     page    → fetch Page:.../N, upsert (+ pagequality level)
     transclusion → scan mainspace transclusions, fan out
4. update progress_done/total; roll parent's aggregate up
5. status → done | error
```

Concurrency uses the documented SQLite discipline: WAL, `busy_timeout=5000`,
`BEGIN IMMEDIATE` for every write — on both the Python and Kotlin sides.

---

## 8. Open decisions

1. **Transport: shared-SQLite (WAL) vs REST.** `schema.sql` is written for the
   shared-DB topology (plugin and pywikibot both open `database.db`). FastAPI
   gives easier debugging and a CLI/HTTP inspection surface. These aren't
   exclusive — recommendation: **FastAPI as the plugin-facing contract**
   (surfaces A/B/commit above), with SQLite underneath; revisit raw shared-DB
   only if HTTP latency on the VFS hot path proves to be a problem.
2. **SQLModel vs Django.** Django buys free admin/inspection/rendering of cached
   data. Current stack (SQLModel + FastAPI + Typer CLI) is lighter and already
   started. Recommendation: stay on SQLModel until the data model is settled
   (this doc), reassess once there's real cached data to inspect.
3. **Namespace ids per site.** `Page:`=104 / `Index:`=106 are the common
   Wikisource values but should be read from each site's `siteinfo`, not
   hardcoded — store them on `sites` / `Namespace`.

---

## 9. Testing

A local Wikisource runs at `https://wikisource-debian-13.lan` with a known work:

```
Index:Wittgenstein_-_Tractatus_Logico-Philosophicus,_1922.djvu
Book:Tractatus_Logico-Philosophicus
```

This lets us exercise fetch → edit → commit end-to-end without touching live
Wikisource. First integration target: a single `kind=index` fetch of the
Tractatus that produces one `File:` blob on disk, N `Page:` rows, and a watchable
parent request.
