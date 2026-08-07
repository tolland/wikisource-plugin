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
  with the first `origin` winning. Page-level correspondence is *derived* by
  `corresponding_page` walking `link → revision → page`, in either direction;
  a target redlink has no link, which is correct — there is nothing to compare,
  and "local present, target absent" is a pairing question, not a linking one.
  `origin=reconciled` records the forward re-anchoring of discussion §2.

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

### 4. `wtctl sync --from Index:X [--to Index:Y]`

The happy path, end to end. `--to` is only needed when the titles or namespaces
differ.

- [ ] Enumerate both indexes via `list=proofreadpagesinindex` (authoritative
      pagination, missing slots reported as `pageid` 0).
- [ ] Run the §6 scan check first — differing backing files means the page
      offsets do not correspond and nothing below is trustworthy.
- [ ] Produce a **ladder** per page: the ordered `RemoteLink` rows, and the
      current anchor. Where a pair cannot be matched, say so and why, rather
      than guessing.
- [ ] Output is a report, not an edit. No writes to either wiki.

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

**Only heads are compared, and that is the answer to "which revision do we
link".** Finding the revision in their history matching ours has no single
answer: null and touch edits leave runs of byte-identical revisions (four in
the Canadian patent fixture; en.wikisource ran a whole `Pywikibot touch edit`
campaign in 2018), so a content match lands anywhere in the run with nothing
to choose between members. The question is also one §2 already declined —
remote history is append-only, there is no merge base to discover, the anchor
is recorded on pull and re-established by hand when it breaks — and our
revision store is deliberately sparse, so a walk would be bounded by our
sampling rather than by the wiki's history. Heads have exactly one revision
per side.

Were a historical base ever wanted, the rule would be **the newest revision of
a content-equal run**: every member is equally true, so the newest is the
tightest claim, and an older anchor makes a page look diverged when it is not.

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

```bash
docker compose -f compose.seeded.yml --profile pair up -d --wait

# ...and the API too, for anything that should speak HTTP rather than reach
# into the ASGI app in-process:
docker compose -f compose.seeded.yml -f compose.wtbot.yml \
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
