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

### Namespaces we care about — by role, never by hardcoded id

**Numeric namespace ids are per-site and must not be hardcoded.** When the
ProofreadPage extension is reinstalled on a fresh wiki it gets deconflicted ids
(`Page`=250, `Index`=252), whereas en.wikisource.org still runs the legacy ids
(`Page`=104, `Index`=106). Custom namespaces (e.g. a dedicated `Book`=3100 for
moving mainspace works) are operator-chosen and differ per install. So the only
portable thing is the **canonical namespace name**, which *is* stable across
sites — `Page`, `Index`, `File`, `Template`, `Module` are the same string
everywhere; only the integer key moves.

The backend therefore works in terms of a **role** (an enum), and resolves
role → local numeric id per-site from `siteinfo`:

| Role        | canonical name | en.ws | local (PRP reinstall) | Treatment                              |
|-------------|----------------|-------|-----------------------|----------------------------------------|
| `INDEX`     | `Index`        | 106   | 252                   | ProofreadPage index — root of a work   |
| `PAGE`      | `Page`         | 104   | 250                   | one scan page's transcription (`…/N`)  |
| `FILE`      | `File`         | 6     | 6                     | backing DjVu/PDF — **file, not a row** |
| `MAIN`      | (empty)        | 0     | 0                     | article / composed work                |
| `BOOK`*     | `Book`         | —     | 3100 (custom)         | collection/landing (site-configured)   |

\* `BOOK` is not a standard Wikisource namespace; on en.ws works live in `MAIN`.
It's an operator convention, so its name/id come from per-site config, not a
global assumption. Role resolution falls back to "by name from siteinfo"; only
genuinely custom roles need a per-site override.

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

**Resolved.** There were two divergent definitions; they have been merged into
the SQLModel classes under `wtbot/sqlmodel/`, which are now the **single source
of truth**. The hand-written `schema/schema.sql` has been deleted — keeping a
parallel DDL file split the authority of the model.

What was carried across from the old `schema.sql`: the rich `pages` shape (inline
remote-identity/conflict columns), `transclusions`, the fetch queue
(`fetch_requests` → `FetchRequest`), and the outbound `commits` log (→ `Commit`).
Site identity is the pywikibot `family`/`code` pair (the request vocabulary
`title:x family:y code:z`); `host`/`api_url` are derived/optional columns, not the
key. The old standalone `Revision` model was folded into `pages` (inline remote
state, matching the original schema design) and `upserts.py` was removed as stale.

Two things deferred, not lost:
- **FTS5** (`pages_fts`) for "search/replace across the whole work" — was a
  virtual table in `schema.sql`; will return as a raw-DDL migration step, since
  SQLModel doesn't model virtual tables.
- A real **migration tool**; `init_db()` is create-if-absent for now.

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

### 6.3 Per-site namespace map (role → local id)

`Namespace` becomes **per-site** and role-aware. We never compare numeric ids
across sites; we compare roles. The map is populated from each site's `siteinfo`
on first contact.

```python
# wtbot/sqlmodel/namespace.py  (proposed — replaces the flat model)
from enum import Enum
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint


class NsRole(str, Enum):
    main = "main"
    page = "page"      # ProofreadPage Page:
    index = "index"    # ProofreadPage Index:
    file = "file"
    template = "template"
    module = "module"
    book = "book"      # site-custom (operator convention)
    author = "author"
    other = "other"


class Namespace(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("site_pk", "key", name="uq_ns_site_key"),
    )
    pk: int | None = Field(default=None, primary_key=True)
    site_pk: int = Field(foreign_key="site.pk")
    key: int                      # the site-local numeric id (104 or 250 …)
    canonical_name: str           # 'Page', 'Index', 'File' — stable across sites
    local_name: str               # display name on this wiki (may be localized)
    role: NsRole = NsRole.other   # resolved from canonical_name (+ site overrides)
```

`pages.namespace` should then store the **role** (or FK the `Namespace` row),
not a bare integer, so a Page from a 250-wiki and a Page from a 104-wiki are
recognisably the same kind of object. Roles are assigned by matching
`canonical_name` against the standard set, with a small per-site override map for
custom namespaces like `Book`.

### 6.4 The journal (separating saves from cached remote state)

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

The worker (`wtbot/worker.py`) drives surface B:

```
1. claim a pending FetchRequest (highest priority first) -> in_progress
2. build a WikiClient for the request's Site (client factory; injectable)
3. fetch the title, upsert into `pages` (body, content_model, revid, sha1, ...)
4. [next] index fan-out: download File: to cache/blobs/...; read page_count;
          create child `page` FetchRequests (parent_pk = this)
5. update progress_done/total; status -> done | error
```

**Implemented now:** steps 1-3 and 5 as `run_pending(session, client_factory)`,
processing a single title per request and writing the page back. **Next:** the
index fan-out (step 4) and the File: blob download, which slot into the marked
point in `worker._process` and are fully testable via `FakeWikiClient`.

**Who runs it.** Today the `POST /fetch` endpoint enqueues the request and then
calls `run_pending` *inline*, so one HTTP call does enqueue → drain → write-back
(the CLI's `fetch-page` just calls this endpoint over HTTP; it no longer touches
pywikibot itself). `run_pending` is deliberately transport-agnostic so the same
function backs a future background loop / `wtbot worker` command without change.

Concurrency uses the documented SQLite discipline: WAL and `busy_timeout=5000`
on every connection. (An earlier rule additionally forced `BEGIN IMMEDIATE` on
every transaction so the write lock was held for the whole request; holding the
lock across request handling proved unreliable and was reverted to the driver's
normal deferred locking — under WAL, readers need no lock at all.)

The wiki call goes through the injectable `client_factory` on `app.state`, so
tests drive the whole endpoint with a `FakeWikiClient` and no network.

### 7.1 Wiki access seam + config injection (implemented)

pywikibot's tutorial flow wants a hand-written `user-config.py` plus family
files. That doesn't fit a backend driven from three places — pytest, the Typer
CLI, and an IntelliJ-launched process. So wiki access is behind an injectable
seam (`wtbot/wiki/`):

- **`WikiSettings`** (`wtbot/settings.py`) — the one config object: `family`,
  `code`, optional `api_url`, `username`, `ca_bundle`, `config_dir`. Built inline
  in tests, from flags/env in the CLI (`from_env`), or from a `Site` row
  (`from_site`). Reads are anonymous; `username` is only for write-back.
- **`configure_pywikibot()`** (`wtbot/wiki/config.py`) — applies settings
  *programmatically*: `PYWIKIBOT_NO_USER_CONFIG=1` (no file on disk), an ephemeral
  `PYWIKIBOT_DIR`, `REQUESTS_CA_BUNDLE` for a self-signed `.lan` cert, and
  `Site(url=...)` (AutoFamily) so **no family file is needed**. pywikibot is
  imported lazily, after the env is set.
- **`WikiClient`** Protocol (`wtbot/wiki/client.py`) — `get_page` +
  `download_file`. `PywikibotClient` is the real impl; `FakeWikiClient` is the
  in-memory one tests/CLI use, so the fake path never imports pywikibot.

### 7.2 Dispatch: trust content_model, special-case File (implemented)

How a fetched object is handled is decided by its remote **`content_model`**, not
by parsing the title ourselves: an Index reports `proofread-index`, a Page
reports `proofread-page`, a plain article reports `wikitext`. We rely on
pywikibot's ProofreadPage object model anyway, so the remote's own classification
is the right source.

The single override is the **File namespace**: a `File:` page's content_model is
plain `wikitext` (that's its *description* page), but the payload we want is the
binary scan — so the namespace decides before content_model does.
`wtbot/wiki/dispatch.py`:

```
classify(content_model, namespace_role) -> Handling
   namespace_role == file        -> FILE              (download the binary)
   content_model 'proofread-index' -> PROOFREAD_INDEX (pagelist, File, fan out)
   content_model 'proofread-page'  -> PROOFREAD_PAGE  (transcription + quality)
   content_model 'wikitext'        -> WIKITEXT        (mainspace, Book, Author)
   else                            -> UNKNOWN
```

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
3. ~~Namespace ids per site.~~ **Resolved** (§3, §6.3): work in terms of a
   role enum, resolve role → local numeric id from per-site `siteinfo`, never
   hardcode `104`/`106`.

---

## 9. Cross-wiki correspondence (staging ↔ upstream)

A central future use case: a local wiki is a **staging copy** of an upstream one.
`https://wikisource-debian-13.lan/.../Index:…Tractatus…djvu` is the local staging
of `https://en.wikisource.org/.../Index:…Tractatus…djvu`. We want to iterate
locally, then later `fetch`/`pull`/diff/rebase against the canonical wiki, and
surface that relationship to IntelliJ (compare staging vs canonical, pull
updates, view diffs).

This is intentionally **designed-for, not built-now** — but the foundations are
already present and we just need to not paint ourselves into a corner.

### Why this is hard, and why we're mostly OK

The two trees are independent wikis. `pageid` and `revid` are wiki-local and
**not comparable** across them (the schema already calls this out). What *is*
comparable:

- **Title** — the logical handle; usually identical on both sides, but may be
  deliberately renamed in staging, so it can't be the sole link.
- **`sha1`** — MediaWiki's content hash of revision text. Byte-identical content
  yields the same `sha1` on *both* wikis regardless of revid. This is our
  cross-wiki "same content" oracle.
- **structure** — Index → Pages parent/child trees line up by `page_number`
  within a work even when ids differ.

So we don't try to reconcile ids. We assert correspondence explicitly and use
`sha1` as the merge-base oracle — exactly git's model: a remote-tracking ref plus
a recorded merge base.

### The link object

```python
# wtbot/sqlmodel/remote_link.py  (proposed, future)
from datetime import datetime
from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint


class RemoteLink(SQLModel, table=True):
    """One local page's tracking relationship to the same logical object
    on another site. Analogous to a git remote-tracking ref + merge base."""
    __table_args__ = (
        UniqueConstraint("local_page_pk", "upstream_site_pk", name="uq_link"),
    )
    pk: int | None = Field(default=None, primary_key=True)

    local_page_pk: int = Field(foreign_key="page.pk")
    upstream_site_pk: int = Field(foreign_key="site.pk")
    upstream_title: str                     # may differ from the local title

    # merge base: the upstream revision we last synced FROM. sha1 is the
    # cross-wiki-stable token; revid/pageid are kept only as upstream-local hints.
    base_sha1: str | None = None            # content we last reconciled against
    base_revid: int | None = None           # upstream-local, informational
    base_synced_at: datetime | None = None

    # last seen upstream head (refreshed by a cheap metadata poll)
    upstream_head_sha1: str | None = None
    upstream_head_revid: int | None = None
    upstream_checked_at: datetime | None = None
```

Links are seeded by an explicit **clone** operation rather than guessed. The
planned CLI form:

```
wikictl clone --src wikisource:en --dest mywikisource:en \
              --index Index:some_book_of_interest.djvu
```

`clone` fetches the work from `--src`, writes it into `--dest`, and builds the
`RemoteLink` rows (Index + each Page) as it goes — so correspondence is asserted
at creation time, when titles and structure are known, and survives later
renames in staging. Links attach at the page level; an Index-level link plus
matching `page_number`s lets the whole work be tracked from one clone.

### The three-way state (drives pull / rebase / diff)

For a linked page, compare three content hashes — local body `sha1`,
`base_sha1`, and freshly-fetched `upstream_head_sha1`:

| local vs base | upstream vs base | meaning            | action exposed to IDE        |
|---------------|------------------|--------------------|------------------------------|
| same          | same             | in sync            | (nothing)                    |
| changed       | same             | local-only edits   | ready to push upstream       |
| same          | changed          | upstream advanced  | **fast-forward pull**        |
| changed       | changed          | diverged           | **diff + 3-way merge/rebase**|

Fast-forward updates `base_*` to the new upstream head. Divergence surfaces a
diff in IntelliJ (it already does PSI-level wikitext); a "rebase" replays local
journal edits onto the pulled upstream body. None of this needs id reconciliation
— it's all `sha1` and body diffs.

### Operations (future surface)

```
POST /link        { local_title, upstream:{family,code}, upstream_title }
GET  /link/{page} → { state, base_sha1, upstream_head_sha1, diff_url? }
POST /link/{page}/refresh    # cheap upstream metadata poll, update head sha1
POST /link/{page}/pull       # ff if clean; else return diff for merge
```

### What we do now vs later

- **Now:** keep `sha1` populated on every fetched revision (already in the
  schema), keep titles and Index→Page structure intact, and don't assume ids are
  global. That alone keeps the door open.
- **Later:** add the `RemoteLink` table and the link/pull endpoints. No change to
  the core `pages`/journal model is required to get there — `RemoteLink` is purely
  additive.

---

## 10. Testing

A local Wikisource runs at `https://wikisource-debian-13.lan` with a known work:

```
Index:Wittgenstein_-_Tractatus_Logico-Philosophicus,_1922.djvu
Book:Tractatus_Logico-Philosophicus
```

This lets us exercise fetch → edit → commit end-to-end without touching live
Wikisource. First integration target: a single `kind=index` fetch of the
Tractatus that produces one `File:` blob on disk, N `Page:` rows, and a watchable
parent request.
