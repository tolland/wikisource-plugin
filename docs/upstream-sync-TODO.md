# Upstream sync — TODO

The immediate work list. Reasoning, rejected approaches and policy live in
`upstream-sync-discussion.md`; measured ProofreadPage hash behaviour lives in
`proofread-page-sha1-discordance.md`.

## Built

- **Revision store** — `page → revision → slot → content`, mirroring MediaWiki's
  schema. `slots` kept because Commons `File:` pages really are multi-slot
  (`main` + `mediainfo`), including the Hertz scan. Content is addressed by our
  own hash of the served bytes; `Content.remote_sha1` carries the wiki's for
  corroboration only.
- **Fetch worker populates it** on every fetch, recording the head revision.
  `Page.text`/`revid`/… remain the head denormalisation.
- **`wtbot.wiki.sha1`** — the two MediaWiki hash encodings (API hex vs
  dump/database base-36) and a locally computed content hash.
- **Two-wiki test harness** — `docker compose --profile pair`, upstream + local
  on 18581/18582, real dumps imported with history, pywikibot bound to each,
  and direct SQL access to the wikis' own databases.
- **Content-model-aware comparison** (`wtbot.content_model`) — the replacement
  for cross-site hashing. A `ProofreadPageDocument` splits a body into header /
  body / footer / level / user and compares them by what they mean:
  - header, body and footer are comparable (a running header is a real
    difference, so the header is compared with the pagequality tag removed
    rather than ignored wholesale);
  - `level` is comparable **and directional** — equal words do not make it safe
    to overwrite, so `quality_delta` and `is_downgrade` are part of the result;
  - `user` must be present but is never compared — it names an account on one
    wiki.

  The verdict is a `Significance`, not a boolean: `identical`,
  `metadata_only` (same transcription, different attribution — the cross-site
  norm), `metadata_significant` (same words, different proofreading state) or
  `content`. Tested against the real Canadian patent revisions, including a
  lossless parse/serialize round-trip over every one of them.

- **Migration discipline** — never `batch_alter_table` on a table something
  references; `test_migrations.py` runs migrations over populated tables.

- **Site identity discipline** — a wiki is registered once, by `label`, and
  never conjured from a request. Taking `family`/`code`/`api_url` per request
  meant a typo registered a new wiki with no credentials and read from it
  anonymously. `test_site_identity.py` enforces it rather than leaving it to be
  re-audited: only the CRUD router may construct a `Site`, no request *body*
  outside it may name a wiki's location, and the viewer's `FetchCreate` must
  send a label. Reading those fields is fine — displaying them, deriving an OCR
  scope from them, looking a site up by them (a lookup returns None where a
  create would have invented one).

- **`RemoteLink`** — the assertion that **two revisions, one per site, are the
  same content**. Asserted and recorded, never computed from hashes (discussion
  §3: a `pagequality` header makes cross-site hashes disagree precisely as
  proofreading progresses).

  ```python
  class RemoteLink(SQLModel, table=True):
      __table_args__ = (
          UniqueConstraint("local_revision_pk", "remote_revision_pk", name="uq_link"),
      )
      pk: int | None = Field(default=None, primary_key=True)

      local_revision_pk: int = Field(foreign_key="revision.pk", index=True)
      remote_revision_pk: int = Field(foreign_key="revision.pk", index=True)

      origin: LinkOrigin          # copy | title_match | manual | reconciled
  ```

  Four fields from the original sketch were dropped rather than carried
  unread: `confidence` (a proposal's score belongs to the proposal — a link we
  are not confident in should not be stored at all), `note`, `asserted_by`, and
  `asserted_at`. Ordering — which is all "the most recent link is the anchor"
  actually needs — comes off the monotonic `pk`, and a wall clock would be a
  second, less reliable answer to the same question. Add any of them back when
  something reads them.

  **The pair is unordered.** `local`/`remote` record the direction an assertion
  was made from — which side `origin=copy` copied from, which site the operator
  was looking at — but neither is privileged, so "A corresponds to B" and "B
  corresponds to A" must be one row, not two. Two rows would give a page pair
  two ladders and two anchors that could disagree, and every layer above would
  inherit the error. Enforced in the database, not only in the store:
  `uq_remotelink_pair` is unique over `min(local, remote), max(local, remote)`,
  which SQLite can index because it indexes expressions. Every read matches a
  pair in either orientation.

  Enforced in `wtbot.remote_link_store`, the only writer: append-only (no
  update, no retract), cross-site only (within one wiki, revision ancestry
  already says everything a link would), and idempotent on the unordered pair
  with the first `origin` winning. `origin=reconciled` records the forward
  re-anchoring of discussion §2.

- **`PageLink`** — the pairing the revision links hang off. This **reverses** an
  earlier decision to derive page correspondence from the links
  (`corresponding_page` walking `link → revision → page`). Derivation was wrong
  three ways, each visible the moment a person looks at a work:

  - a pair with nothing linkable is unrepresentable — a diverged pair, or one
    whose other side is unfetched, derives into nothing, and those are exactly
    the pairs that need attention;
  - titles are not stable, so a page moved on either wiki broke any pairing
    recomputed from them;
  - a work's pairs could not be enumerated without re-deriving the whole index,
    which is the first thing the viewer needs.

  The two are different kinds of claim, and the split follows. `PageLink` —
  "these two pages are the same page" — is about the present, can be wrong, and
  has a `DELETE` that takes its rungs with it. `RemoteLink` — "these two
  revisions hold the same content" — is about two immutable objects, so it is
  superseded, never edited. Both are unique on the unordered pair, and a rung
  follows its pairing's orientation so a ladder reads one way round.

  `POST /links/pairs/index` (`wtbot link pair-index`) pairs a whole work before
  any content is compared, refusing by default if pages do not line up — a work
  missing counterparts is nearly always a wrong `--to` or a different scan.
  `GET/POST/DELETE /links/pairs` is the CRUD the viewer drives.

  Retraction comes in two widths, because wanting a ladder gone is not wanting
  a pairing gone. `DELETE /links/pairs/{pk}` (`wtbot link unpair`) discards
  both. `DELETE /links/{pk}` and `DELETE /links/pairs/{pk}/rungs`
  (`wtbot link unpair-revision`, by rung or `--pair` for a whole ladder) retract
  the revision links and keep the pairing — which is what a bad `propose` run
  actually calls for: the links were wrong about the *revisions*, and re-pairing
  a work before it can be re-proposed is busywork that also loses the pair's
  page numbering and its place in the work's listing.

- **`IndexLink`** — the work-level correspondence, and the viewer's entry point.
  For Wikisource the unit of comparison is the Index, not the page: pages are
  compared and promoted *within* a work, and "is this work tracked upstream?" is
  the question asked first. It is a **side table on `PageLink`**, the way
  `IndexMeta` is on `Page` — an `Index:` page is a page, so pairing two of them
  is already a `PageLink`, with a ladder over the index bodies (which diverge
  like any other) for free. A second pairing table would mean two places that
  can assert page correspondence and two unordered-pair constraints that cannot
  see each other. `PageLink.index_link_pk` points children at their work so the
  drill-down is a join, and stays **nullable**: a mainspace or `Portal:` pairing
  is a legitimate standalone row, which is what generic MediaWiki use needs.

  Three levels, `/links/works` and `/links/pairs/{pk}/revisions`, with the
  viewer route `/links` on top:

  1. **works** — two site columns, indexes below each, tracked pairs pinned
     above. `wtbot link works` / `track-work`.
  2. **page pairs** — one work's pages with a live outcome each, plus the two
     actions the unresolved outcomes call for: `fetch-history` (queues deeper
     fetches for the pages whose anchor search ran out) and `propose`.
  3. **revisions** — both histories side by side, joined on `comparable_sha1`.
     This exists because the anchor search compares each head against the other
     side's history *one side at a time* and stops there: a page where both
     sides edited after they last agreed gets no proposal even though the
     matching pair is one revision back on each side. The view shows it, and
     `POST /links/pairs/{pk}/rungs` lets a person assert it (still refusing a
     non-matching pair without `force`). `wtbot link revisions [--link-best]`.

  Deliberately absent: anything that changes a proofreading level. Two sides
  still differing in level with complete history disagree about an assessment,
  and resolving that is an edit through the commit path, not a link operation.

- **`Content.comparable_sha1`** — the content-model comparison's verdict,
  precomputed. Hashing the bytes cannot decide cross-site sameness (discussion
  section 3); hashing the *normalised* form can, and does. Equal digests mean
  the comparison would return `same_transcription` at a significance other than
  `metadata_significant`, which is the predicate the anchor search runs — so the
  search compares strings across a page's history and parses only the revision
  it settles on. Compared only within one content model, and a null digest falls
  back to the full comparison. See discussion section 3a.

## Now

Numbered as originally listed; items 1 (`RemoteLink`) and 3
(content-model-aware comparison) are done and moved to *Built* above.

### 2. Incremental fetch

Refresh a curated subset without refetching everything. Built on
`list=recentchanges` rather than the `probe_pages` sketch below, and it is
*planning* only: the titles it produces go to the ordinary fetch queue, so
there is one fetch mechanism and a shorter list — not a second path.

`POST /fetch/refresh { family, code, title_prefix?, since?, dry_run? }` →
`wtbot.incremental.plan_refresh`, or `wtbot fetch-refresh` from the CLI. The
request and response are typed (`RefreshCreate`/`RefreshResult`), so Swagger
renders described fields and an example rather than an opaque JSON blob, and
`basis` reaches the caller as an enum rather than a string in a dict.

- [x] **The recentchanges table is pruned** (`$wgRCMaxAge`, 90 days by
      default). Past that horizon "nothing changed" and "the wiki no longer
      remembers" are the same empty response — so the oldest retained entry is
      asked for (one request), and a watermark older than it downgrades the
      plan to a full pass. The result carries its `basis`
      (`incremental` | `full`) and the reason: a caller that cannot tell the
      two apart cannot tell "two pages moved" from "we gave up and listed
      everything".
- [x] **The watermark is the newest change seen, not `now`.** An edit saved
      during the query can carry a timestamp earlier than the moment we
      finished reading. `rcstart` is inclusive, so passing the observed maximum
      back re-reads that instant — duplicates, which a fetch absorbs, rather
      than a gap, which it does not. Stored per site
      (`Site.changes_seen_through`), advanced only on an incremental plan.
- [x] **Namespace ids are per-site**, so the `rcnamespace` filter is resolved
      from this site's `Namespace` rows by role. An unresolved table sends no
      filter at all: an empty `rcnamespace` matches nothing, which looks
      exactly like a wiki where nothing ever changes.
- [x] **A changed revid is not a changed page.** Null and touch edits bump the
      revid with identical content (four such in the Canadian patent fixture).
      This produces candidates, never verdicts; "diverged" comes from the
      content comparison after fetching, or every upstream maintenance run
      shows up as a false conflict.
- [x] There is no `rcprefix` — `rctitle` filters to a *single* page — so
      narrowing to one work is done here, over metadata already paid for. With
      a prefix, titles we do not yet hold are taken too: that is how a
      partially transcribed index grows.

Not covered, and deliberately not half-covered:

- [ ] **Moves and deletions.** They are `log` entries needing
      `list=logevents`, and discussion §5 wants them *classified*
      (`redirect`/`deleted`/`moved`), not merely noticed. `rctype` stays
      `edit|new` so the gap is visible rather than apparently handled.
- [ ] `probe_pages(titles)` over `prop=revisions`, 50 titles per request, as
      the complement: bounded by the size of the work rather than by wiki
      activity, and with no retention horizon. Worth having for the "watermark
      is ancient" path, which currently refetches everything known.
- [ ] This is for *planning*, not safety. The `baserevid` precondition covers
      the race between fetch and push; they are complementary.

### 4. `wtbot sync report --from Index:X [--to Index:Y]`

Built: `wtbot.sync` + `POST /sync/report` + the `/sync` viewer route.

- [x] **Directional**, unlike everything under it. A pairing and a rung are
      unordered claims — "A corresponds to B" is the same fact as its reverse —
      but a sync asks what would be *written* and to *which* wiki, so reversing
      it reverses the answer. Hence `SyncVerdict` rather than reusing
      `MatchOutcome`: `local_ahead` is a fact about a pair, `push` is a fact
      about a direction. The viewer's swap button is the whole difference.
- [x] **Addressed by title, not by a tracked work.** The case most in need of a
      report is the one where the target index does not exist yet (§7), and
      there is no pairing to key on until it does. An absent target index is a
      blocker reported *alongside* the page list, not instead of it: seeding a
      work from upstream is a thing people do, and the page list is what they
      came for.
- [x] Pagination comes from the cache, which is `list=proofreadpagesinindex`
      one step removed — that call is what the index fan-out already makes, and
      the placeholder rows it writes are its record. `cached_pages` says how
      much is held, so a shallowly fetched work does not read as a complete one.
- [x] **The §6 scan check runs first**, and its result is on the response
      whether it passed or not: "we checked and they match" and "we could not
      check" are different claims. `mismatch` blocks. A target with no `File:`
      is `unverifiable`, not a block — an index without a file is legal, but
      nothing then validates the page correspondence.
- [x] Per page: the anchor revids, the ladder depth, and how far each side has
      moved. Where a pair cannot be matched the matcher's own reason is
      carried through rather than flattened to "no".
- [x] **Three kinds of absence, distinguished.** No target index (whole work is
      a create); no target row (that page is a create); a target row with no
      revision — a **placeholder**, the stub the fan-out writes for a paginated
      slot nobody has transcribed. The last is a `create`; a row we merely have
      not fetched is `unknown`, because writing it as a create could clobber a
      page somebody else wrote. Read through `head_revision`, not `Page.revid`:
      the head columns are a denormalisation with more than one writer.
- [x] **Output is a report.** No writes to either wiki, and none to the local
      model — not even the pairings it reads. Tracking a work stays a separate,
      deliberate act, or "just show me" becomes the most consequential button
      on the page.

- [x] **A work is not only its pages.** The `Index:` and the backing `File:`
      are reported as *assets*, each with what each side holds. The two
      commonest reasons a sync cannot proceed live here rather than in the page
      list: no index on the target, and a scan check that could not run.
- [x] **"Could not check" is a question, not a verdict.** Both of those mean
      nobody has asked the wiki yet, so the report carries a `fetch_plan` and
      `POST /sync/fetch-assets` (`wtbot sync fetch-assets`) queues exactly it —
      the target index, and whichever side's scan is missing. Assets only, and
      `kind=single`: this is a yes/no probe, and fanning the index out would
      make "check the scan" cost a whole work of throttled requests. A scan
      hosted on Commons is followed by the existing
      `_resolve_file_page` → `site.image_repository()` path.
- [x] The file title comes from the index title (`Index:Foo.pdf` →
      `File:Foo.pdf`), which is ProofreadPage's structural rule and what the
      fetch fan-out already uses, so the two agree by construction.

- [x] **An anchor found is not an anchor asserted.** A `push` replays *onto*
      the anchor, and `find_anchor` will happily produce one for a pair nobody
      has linked — that is what it is for. Reported as `push` either way (the
      pair really does hold the same content), but each row carries
      `anchor_asserted`, and the report separates `actionable` from `ready`:
      a create needs no anchor, a push needs a recorded one. The gap is an
      *advisory*, not a blocker — nothing is wrong with those pages, there is a
      `propose --confirm` nobody has run — and advisories are kept apart from
      blockers so that collapsing the two does not teach a reader to ignore
      both.

      Found on a real 316-page Hertz run: 93 pushes, of which only 5 sat on an
      asserted anchor. The other 88 were correct and unsanctioned, and the
      report could not tell them apart.

Uploading a backing scan the target genuinely lacks stays out: that is a
case-by-case decision (discussion §7), not something a sync does.

Still to come, and it is item 6's job rather than this one's: turning a
`create`/`push` row into an actual edit. The report is the preflight that
queue will read.

### 5. RemoteLink proposal endpoint

Built: `wtbot.matching` + `POST /links/propose`, `POST /links`, `GET /links`,
and `wtbot link propose|add|show`.

- [x] `POST /links/propose { local, remote, index_title, remote_index_title? }`
      → a proposal per page pair with an outcome, plus counts. Outcomes are
      `same`, `quality_differs`, `diverged`, `no_counterpart`, `unfetched`,
      `already_linked` — distinct because the ways a pairing fails need
      different actions, and a boolean-plus-message loses which.
- [x] `POST /links` to confirm one pair by title. `DELETE` to retract is still
      absent, and stays absent while links are append-only.
- [x] Title normalisation compares namespace *roles* resolved per site, never
      numeric ids. Pages pair on **page number within the index** rather than
      title text: `--to` exists because the titles can differ, and the scan
      offset is what has to line up (§6). Title equality is only a fallback for
      pages with no number.
- [x] Never auto-confirm. `propose` writes nothing without `confirm`, and
      `confirm_proposals` refuses a non-proposable pair rather than skipping it
      — silently skipping is how "confirm everything that looked fine" creeps
      back in.

**The anchor is searched for in history, not assumed to be the head.** The
common case is not two heads that agree: it is one side imported at some past
revision of the other, with edits since. Hertz page 9 is the shape — a local
import matching upstream's second-newest revision, with a proofread bump on top:

```
local head r10779  level=1 Admin
  …
  r15757193  level=1 Tolland  -> metadata_only        ← the anchor
  r15757208  level=3 Tolland  -> metadata_significant ← head
```

Comparing heads alone reports "same words, different level" and offers a link
asserting sameness of two revisions that are *not* the same — and destroys the
useful fact, which is that upstream is exactly one edit ahead of a base we hold.
So `quality_differs` is **not** proposable, and each head is compared against
the other side's stored revisions, newest first.

Where several revisions match — a run of null or touch edits — the **newest**
wins: every member is an equally true claim, so the newest is the tightest, and
an older anchor reports touch edits as unsynced work.

The search is bounded by what the store holds, which is deliberately sparse, so
the outcomes distinguish **`history_exhausted`** ("no anchor in what we hold,
and we do not hold it all") from **`diverged`** ("held in full, nothing
matches"). Only the first is fixed by fetching, and
`Page.history_complete_from_revid` is what tells them apart — set by walking
`parent_revid` back from the head, so a head whose parent we lack claims
nothing while a head with *no* parent is a complete one-revision history.

Feed it with `wtbot fetch-page --revisions N` (`FetchRequest.revisions`, which
fan-out children inherit).

"Same content" is decided by the content-model comparison, not by bytes or
sha1: a `pagequality user=` names an account on one wiki, so equivalent
transcriptions routinely differ. `metadata_significant` (same words, different
level) is proposable but reported separately, because level is directional.

### 6. `Promotion` / `PromotionBatch` schema

The push queue: mutable, reviewable, cancellable — deliberately not a status
column on an audit log (discussion §12).

- [ ] `PromotionBatch`: source site, target site, index, label, status
      (`draft → preflight → approved → running → complete | partial | aborted |
      rolled_back`), approval record.
- [ ] `Promotion` (one per page): the pairing and preflight result — source
      revision, target page, base anchor, computed body, check outcomes, and the
      **pre-push target revid**, which is what rollback targets and must be
      persisted.
- [ ] Intent (`create` | `update`) recorded explicitly, not inferred from
      `base_revid is None`. This is what lets the push set
      `createonly`/`nocreate` correctly.

### 7. Seeding a work that exists only upstream

The motivating case is `Index:The varieties of religious experience, a study in
human nature.djvu` — present on en.wikisource, absent locally. Two ways to get
it, and they are not alternatives:

1. **`pwb transwikiimport`**, then `wtbot fetch-page` the result:

   ```
   pwb transwikiimport -interwikisource:s \
       -prefixindex:"Index:The varieties of religious experience, a study in human nature.djvu"
   uv run wtbot fetch-page --family mywikisource --code en \
       --api-url https://wikisource-debian-13.lan/w/api.php \
       "Index:The varieties of religious experience, a study in human nature.djvu"
   ```

   Works today, and it transfers *history*, which our own push path structurally
   cannot: every push appends exactly one revision (discussion §2). Keep it as
   the bulk bootstrap.

2. **Downward promotion through `Promotion`/`PromotionBatch`** — item 6 with
   source and target swapped. Same preflight chain, same queue, same audit
   trail. This is what the data model has to support regardless: a set of
   changes derived from another site is the same object whichever way it points,
   and building it only for the outbound direction means building it twice.

The gap between them is what to fix first. (1) copies pages *outside* the data
model, so nothing records that the local revisions came from the upstream ones.
The first sync run then has to re-derive correspondence by title match — the
weaker claim, for a fact that was known at the moment of the import.

- [ ] `wtctl adopt --from <site> --to <site> Index:X` — run after an import,
      match by namespace role + page number, and write `origin=copy` links
      against both sides' head revisions. Cheap, and it turns a title guess back
      into a recorded fact.
- [ ] **Not `EditJournal` + the commit worker.** The two-step (stage, then
      apply) is right, but the journal is the *local per-save* transaction log;
      putting cross-site intent in it repeats the overloading discussion §12
      identifies in `Commit`. Stage in `Promotion`, which is the table that
      exists for reviewable intent.
- [ ] Assets are the reason this must not stay a pywikibot shell-out: a work
      like Wittgenstein's *Tractatus* carries embedded SVG diagrams, and syncing
      an `Index:` should be able to bring its `File:` dependencies with it.
      That is discussion §7's local-only-`File:` block in reverse, and it needs
      the dependency set to be a thing the model can enumerate.

## Next, agreed but not yet scheduled

- [ ] Rename `Commit` → `PushLog` (discussion §12).
- [ ] Push path: `baserevid` + `createonly`/`nocreate` + error-code mapping +
      post-push content verification (discussion §8). Worth doing independently
      of sync — the silent-overwrite-on-create gap exists today.
- [ ] Normalise the remaining `Page` head columns (`text`, `revid`,
      `remote_timestamp`, `contributor`, `comment`) behind
      `head_revision`/`head_content`, so the denormalisation has one writer.
- [ ] Rollback, before mass promotion ships.

## Testing

**The base state belongs to compose, the deltas to the tests.** Both wikis seed
themselves at startup from one shared anchor (`SEED_DUMPS`/`SEED_SCANS` in
`../compose.yml` → `docker/mediawiki/start-wikisource.sh`), so the pair
starts *converged* — same works, same history, same content — because the two
services are configured identically, not because a builder remembered to run
twice. That was a real bug: only upstream was ever seeded, so every "diverged"
fixture was really "never converged", and the local wiki held a lone `Page:`
with no `Index:` and no `File:` for the scan check to compare.

`compose.yml` seeds no content by default — the pair is exactly the kind of
test scenario that asks for it explicitly:

```bash
SEED_SCANS=djvu SEED_DUMPS=Canadian_patent_29537_all.xml \
    docker compose -f compose.yml --profile pair up -d --wait

# ...and the API too, for anything that should speak HTTP rather than reach
# into the ASGI app in-process:
SEED_SCANS=djvu SEED_DUMPS=Canadian_patent_29537_all.xml \
    docker compose -f compose.yml -f compose.wtbot.yml \
    --profile pair --profile api up -d --wait
```

`compose.wtbot.yml` is an overlay rather than a copy in each base, since the
two bases already duplicate the MediaWiki services and that is the part that
drifts. wtbot's SQLite sits on its own volume and is disposable by design —
everything in it is refetchable or not yet pushed — so `WTBOT_RESET_DB=1`
empties it without rebuilding the wikis, which are the slow half.

`--wait` is only trustworthy because the healthcheck requires a marker written
after the import; without it the extension check goes green as soon as
`LocalSettings.php` exists and tests race the import.

Differences are then made by whoever needs them — `copy_page_to_local`,
`diverge_locally`, `reconcile_to_upstream` in `wiki_harness.scenarios`, one line
each, no scenario enum to trace. Nothing tears the stack down: `wiki_pair` only
ensures it is up, so a failed run leaves something to look at.

**The seeded work is read-only; mutating tests use `SCRATCH_PAGE`.** That
follows from not tearing down — a test that edits an imported page leaves the
pair diverged, and the next run starts from a base that is no longer the base.
The scratch pair is removed before creation as well as after, so a run that
died mid-test cannot hand the next one a page with an unexpected history. A
stack dirtied before this rule existed needs one
`python -m wiki_harness up --rebuild`; `test_the_pair_starts_converged` says so
when it fails.

One deliberate asymmetry, and it is not content: `local` burns a few revision
ids first (`SEED_REVID_BURN`). Two wikis installed from empty and seeded in the
same order otherwise assign the *same* revids to the same pages, and a bug
comparing revids across sites would pass in the fixture while failing against
real wikis.

- [x] The copied-work fixture: copy a page across, link it, and confirm the two
      sides read as the same transcription under different attribution.
- [x] Diverge one side and confirm the anchor falls behind the head — the link
      stays true, the distance from it is what says work has happened.
- [ ] Extend from one page to a whole `Index:`, which is where pagination and
      the scan-offset check (§6) come in.
- [ ] Build the diverged fixture on the two-wiki harness: copy a work across,
      edit both sides, assert the pairing reports divergence rather than
      silently promoting.
- [ ] Two sites with differing `File:` sha1s must refuse to link children.
- [ ] A batch targeting an `is_public` site must not run without an approval
      record.
- [ ] Use the harness as the dry-run sink for the whole batch path before
      anything points at en.wikisource.
