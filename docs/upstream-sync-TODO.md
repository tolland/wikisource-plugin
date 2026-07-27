# Upstream sync — promoting local proofreading to en.wikisource.org

**Status: design / TODO. Nothing here is built yet.**

Taking work done on the local staging wiki (`https://wikisource-debian-13.lan`)
and pushing it back to `https://en.wikisource.org`, page by page or a whole work
at a time. Motivating case, and the acceptance test for the whole feature:

| | |
|---|---|
| local | `…lan/wiki/Page:The_principles_of_mechanics_presented_in_a_new_form_(Hertz,_1894).pdf/101` |
| upstream | `…en.wikisource.org/wiki/Page:The_principles_of_mechanics_presented_in_a_new_form_(Hertz,_1894).pdf/101` |

The Hertz work is **already genuinely diverged** — others have made small edits
upstream, equations were added locally — so it is a real fixture, not a
synthetic one. Anything that works on Hertz works.

Related: `src-py/DESIGN.md` §9 sketches the `RemoteLink` object from the *pull*
direction. This is the push direction and the operational detail.

---

## 1. What exists, and what is missing

Already built, and reusable as-is: `EditJournal` (local save log) → `Commit`
(outbound attempt log) → `commit_worker` (per-page push with `base_revid`
conflict detection, refetch enqueue) → `api/commit.py` → the viewer's staged-edit
review UI. `Site` is multi-instance by `(family, code)`, `SiteCredential` is
per-site, `Page` is keyed `(site_pk, title)`, and `Page.sha1` is populated on
every fetch. Two wikis' worth of pages already coexist in the schema.

Missing:

1. **A parallel model of the target side** to compare against (§3).
2. **A merge base**, without which divergence can only be overwritten (§4).
3. **A producer of edits that isn't a human typing in IntelliJ** (§5).

Everything downstream of "an `EditJournal` row exists for the upstream `Page`
row" is already built. **Promotion should be a producer of journal rows on the
target site's pages, not a second commit engine.**

## 2. Why the push direction is riskier

Pull is private — worst case we clobber our own staging wiki. Push is public and
attributable. The edits themselves are presumably fine; the risks are **volume,
automation optics, and silent systematic error** — a normalisation bug
replicated across 400 pages is embarrassing in a way one bad edit is not, and it
draws attention to automation an observer cannot inspect.

It is all revertible, so the goal is not "never err" but **"every mistake
bounded, visible, and undoable in one action"**. Concretely that means: explicit
human approval per batch, bounded batch size stated before approval, every edit
traceable to a batch, and one-click rollback.

---

## 3. Materializing the parallel tree

### 3.1 The fan-out already does this

`_fan_out_index` (`src-py/wtbot/page_processors.py`) drives off
`list=proofreadpagesinindex`, which returns every slot in an index with
`pageid=None` for the ones that do not exist. Existing slots get a child
`FetchRequest`; missing ones get `_ensure_placeholder_page` — a `Page` row with
`revid=None`, which the VFS already reads as `placeholder=True`. **Running an
`index` fetch against the target site produces the parallel tree with no new
machinery.**

### 3.2 Known-absent vs unknown

The distinction that matters, currently implicit:

| | meaning | authorizes |
|---|---|---|
| `fetch_status=done`, `revid IS NULL` | **known absent** — the index enumerated the slot, the wiki said no | a create |
| `fetch_status=unfetched` / no row | **unknown** — we never asked | nothing |

`_ensure_placeholder_page` sets `fetch_status=done` deliberately ("*We know the
remote state: absent. The fetch is complete.*"). But it is an unnamed two-column
convention, and promotion is the first consumer for which conflating the two is
*dangerous* rather than untidy: absent authorizes a create, and a create against
a page that exists is an overwrite.

- [ ] Name it: an `Existence` accessor (`present` / `absent` / `unknown`) derived
      from those two columns. Derive, don't add a column — but make the fan-out
      the only writer of `revid=None` rows by construction, and test that.
- [ ] **Never fabricate placeholders on the target side to fill in the tree.** A
      local placeholder is authoritative (we made the slot). A target-side
      placeholder is a *cached negative*, and negative caching is exactly what is
      unsafe here.
- [ ] Add `remote_checked_at`. A three-week-old "doesn't exist upstream" is not a
      fact.

### 3.3 Probe, don't mirror

Today the only way to learn anything about a remote page is a full fetch —
content, scan enrichment, OCR body, blob. Far too heavy for a mostly-push target
we don't want to mirror.

- [ ] `WikiClient.probe_pages(titles) -> dict[str, PageProbe]` over
      `prop=revisions&rvprop=ids|sha1|timestamp|user`, 50 titles per request;
      missing titles come back in `query.missing`. One `proofreadpagesinindex`
      call plus `⌈N/50⌉` probes covers a 400-page work in ~9 calls.
- [ ] Full-fetch only where the probe says content actually differs.
- [ ] **`sha1` encoding gotcha — verified, and it bites.** MediaWiki reports the
      same digest in two encodings depending on the surface: the action API
      (hence pywikibot's `Revision.sha1`, hence `Page.sha1` here) gives 40-char
      **hex**, while the XML export and the `rev_sha1` column give 31-char
      **base-36**. Intersecting one against the other matches nothing, so
      identical pages read as "unrelated histories". `wtbot.wiki.sha1`
      normalises; everything comparing hashes must go through it.
- [ ] Second `sha1` gotcha: our promoted body is transformed (§5.2), so hash
      equality is a sufficient but not necessary same-content test. Use the
      *transformed* body's hash for no-op detection.

### 3.4 The pairing matrix

Pairing is an **outer join in both directions** on `(index link, page_offset)` —
not on title, and not an inner join, which would throw away exactly the
present-on-one-side-unknown-on-the-other rows that matter.

| local | target | action |
|---|---|---|
| present | present | compare (§4, §5.1) |
| present | **absent** | create — with `createonly` (§5.6) |
| present | **unknown** | probe first, decide nothing |
| placeholder | present | candidate for *pull*, not push |
| placeholder | absent | skip |
| — | present | target has pages we don't model; surface only |

Against the three tree-shape cases:

- **Index and pages created entirely locally.** Correspondence is free — every
  slot is a create. `Index:Foo.pdf` and `Page:Foo.pdf/101` *can* be created on a
  target with no `File:Foo.pdf`; ProofreadPage permits it. What is lost:
  redlinked file/page-image column, no reference image so nobody upstream can
  proofread or validate it, and `imageforpage` / `defaultcontentforpage` return
  nothing (our enrichment already degrades to `None` gracefully). The one real
  cost is that the §3.5 scan-sha1 check has nothing to compare, making the
  page-offset failure mode *undetectable*. Prominent batch-level warning with an
  override, not a block.
- **Page exists on the target, not yet modelled locally.** The `unknown` column.
  Probe it, fetch if it differs. The anticipated "we fail on comparing
  `base_revid`" is a symptom of acting on `unknown` — with the tri-state
  honoured, the planner simply refuses to classify the slot.
- **Created or edited on the target in parallel.** Not solvable by bookkeeping.
  Solved at push time (§5.6), not at model time.

- [ ] Build pairing as a persisted, inspectable artifact (`PromotionItem`, §7.1),
      not a transient computation. "Show me the join" is the first thing anyone
      wants when a sync looks wrong.

### 3.5 The scan-offset check

- [ ] Compare `FileBlob.file_sha1` of the backing `File:` on both sides. A
      different upload (re-derived DjVu, cropped cover, different page count)
      means local page 101 is **not** target page 101 and every promotion in the
      work is silently off by an offset. **Hard block** — this is the worst
      failure mode available here. Where files differ but page counts match,
      allow an explicit constant offset confirmed against a side-by-side scan
      spot-check.
- [ ] Where the target has no `File:` at all the check cannot run; flag the
      pairing `correspondence_unverified` and carry it to the review UI.

---

## 4. The merge base problem

**This is the crux.** Without a common ancestor there is no merge — only
overwrite. And the local copy was generally *not* created by a recorded clone,
so there is no base on file. Worse, the intuition that "only we have commits on
top of it, so we can just push" fails too: without a base we cannot even tell
which differences are *ours* versus which are pre-existing differences between
the two wikis.

The resolution is a **ladder** — try each in order, and record which rung was
used, because it determines how much the result can be trusted.

### 4.1 Rung 1 — recorded base (clone)

The `wikictl clone` flow from DESIGN.md §9 records `base_revid` / `base_sha1` /
`base_body` at copy time. Correct by construction. Not available for Hertz, and
not available for anything staged before the feature exists.

### 4.2 Rung 2 — discovered base (history intersection)

Both sides are real MediaWikis with full revision history and a per-revision
`sha1`. So compute the merge base the way git does — **intersect the two
histories and take the latest common revision**:

```
prop=revisions&rvprop=ids|sha1|timestamp|user&rvlimit=max   # both sides
base = argmax_timestamp { r in upstream_history : norm(r.sha1) in local_norm_sha1s }
```

- [ ] This subsumes and replaces the weaker "match the local page's earliest
      body" idea — a set intersection handles the `Special:Import` case (whole
      upstream history imported locally, so many revisions match) and the
      copy-paste case (exactly one match) with the same code.
Two findings from building the harness change how this must be implemented.
Both are verified, the second against live en.wikisource.

- [ ] **Get the sha1 encoding right.** The action API (hence pywikibot, hence
      `Page.sha1`) returns 40-char hex; the XML export and `rev_sha1` return
      31-char base-36. Intersecting one against the other matches nothing.
      Normalise via `wtbot.wiki.sha1`.
- [ ] **Never intersect on the server's `rev_sha1` — intersect on a hash you
      compute from the returned content.** For `proofread-page` revisions
      predating ProofreadPage's 2018 reserialization pass, the stored
      `rev_sha1` is *not* the hash of the content the API serves for that
      revision. `Page:Canadian patent 29537.djvu/2` serves three consecutive
      revisions with **byte-identical text under three different declared
      hashes**. Measured on en.wikisource: proofread-page 3 of 4 mismatch,
      proofread-index 11 of 11 match, wikitext 2 of 2 match — so it is specific
      to `proofread-page`, which is exactly the content model this project
      cares about most. `content_sha1_base36` is the token to use; pinned by
      `test_proofread_serialization.py`.

This also corrects an earlier note here claiming ProofreadPage rewrites `user=`
on every save. It does not — the attribute tracks whoever last *changed the
level* and survives saves that don't (`Wikisource-bot` re-saves `Page:…/1` with
the header still crediting `Hesperian`). The real obstacle to rung 2 was never
the header; it is the stored-hash discrepancy above.

- [ ] A *content*-normalised hash (neutralise `pagequality` `user=`/`level=`,
      line endings, trailing whitespace) remains worth having for copies that
      did perturb the text, and it is the same normalisation the comparison
      protocol in §5.2 needs.
- [ ] **Consequence for cost:** intersecting on content hashes means the history
      walk must fetch revision *content*, not just metadata. `rvprop=content`
      with `rvslots=main` still returns up to 50 revisions per request, so it is
      one request per page rather than per revision — but it is no longer the
      cheap metadata-only walk §3.3 describes. Restrict it to pages the probe
      already says differ.
- [ ] Cost is one history call per page per side. Restrict the walk to pages the
      cheap probe (§3.3) already says differ — for a mostly-clean work that is a
      handful of pages, not 400.
- [ ] Fetch the base *body* once found (`rvstartid=<base>&rvlimit=1&rvprop=content`)
      and store it on the link. Historical revisions can later be deleted; a
      recorded `base_body` cannot.

### 4.3 Rung 3 — patch-based promotion (always available)

If rungs 1 and 2 both fail there is no cross-wiki ancestry. **That does not mean
no merge is possible** — because the base needed to know *what we changed* is not
a cross-wiki base at all. It is our own pre-edit snapshot, and that is always
obtainable:

- **Fast path:** `EditJournal.base_revid` already records, per save, the local
  revid the edit started from. For pages edited through the plugin we have
  literally already stored the answer.
- **General path:** the local wiki's own revision history — the revision
  immediately before our first edit.

Given `local_base` and `local_head`, our contribution is `diff(local_base,
local_head)`. Apply that to `target_head` as a three-way merge with
`base = local_base`. Hunks that apply cleanly land; hunks that don't are
conflicts. This is `git rebase` / `format-patch | am -3`, and it works **even
though `local_base` never existed upstream** — we are transplanting a delta, not
asserting shared ancestry.

**This should probably be the default promotion model, not a fallback**, which is
a real shift from "push the transformed local body":

- The local wiki is *staging*. What we want to promote is the changes we made,
  not the state of our wiki. Whole-body promotion silently carries over every
  incidental difference between the two wikis — template conventions, header
  differences, other people's local edits — as though it were our work.
- Others' upstream edits survive by construction: we apply our delta onto their
  head rather than replacing it with our body.
- It matches Hertz exactly — small upstream edits, locally added equations.
  Patch-apply keeps both and conflicts only on genuinely overlapping hunks.

- [ ] Record which rung produced the base on the item, and surface it in the
      review UI. A rung-3 merge is a weaker claim than a rung-1 merge and the
      reviewer should know which they are looking at.
- [ ] The journal body stays a **full body** — the merge *product* — so
      `commit_worker` needs no change. But it must be recomputed if the target
      head moves between preflight and push; the `basetimestamp` precondition
      (§5.6) is what catches that.

### 4.4 Rung 4 — no base at all

Page created from scratch locally, or history unavailable. Base is the empty
string: every promotion is a create, or an add/add conflict if the target turns
out to exist. Honest, and correct — two independent transcriptions of one scan
page genuinely need a human.

- [ ] Represent "no base" explicitly. Do not let it be indistinguishable from
      "never synced" or from a fabricated base.

---

## 5. The promotion pipeline

### 5.1 State classification

Comparing local body, base, and freshly probed target head:

| local vs base | target vs base | state | action |
|---|---|---|---|
| same | same | `in_sync` | nothing |
| changed | same | `local_ahead` | promotable — clean push |
| same | changed | `target_ahead` | nothing to promote; offer a pull |
| changed | changed | `diverged` | merge per §4.3, then review |
| — | — | `target_missing` | create |

`local_ahead` is the only state eligible for bulk auto-approval.

- [ ] "Local body" must be the **effective** body (`PageStore.effective_body`) —
      bridging on an uncommitted local commit if the refetch hasn't landed.
      Promoting a stale snapshot while a newer save sits in the journal is a
      hard-to-spot bug.
- [ ] Block promotion while the *local* page has uncommitted journal rows —
      "commit locally first". Two pending-write concepts on one page is a trap.

### 5.2 Body transformation

The merge product still cannot be pushed verbatim:

- [ ] **`<pagequality>` header** — rewrite `user=` to the account performing the
      push; the local username may not exist on the target.
- [ ] **Quality level** — cap promoted levels at 3 (Proofread). Wikisource
      requires validation be done by a *different* user than the proofreader, so
      asserting level 4 via automation from a staging wiki is exactly the wrong
      look. Never downgrade an existing target level.
- [ ] **Local-only templates / modules** — `{{…}}`, `{{#invoke:…}}` that redlink
      on the target produce visible breakage across every promoted page. Block.
- [ ] **Local-only `File:` references** — `IndexMeta.short_name` generates
      `File:{short_name}_page_101_image_1.jpg` for extracted illustrations. These
      render as redlinks rather than failing the save; block by default, allow an
      override, and see §6.3 on uploading them.
- [ ] **Absolute links to the staging host** — any `wikisource-debian-13.lan`
      URL is a hard block; broken and mildly disclosive.
- [ ] Categories missing on the target — warn.

Implement as an ordered list of named `PromotionCheck` / `PromotionTransform`
classes, each returning `pass` / `warn` / `block` plus (for transforms) the
rewritten body, so the UI can render the chain and new rules are a class rather
than a pipeline change.

### 5.3 Execution, and the `EditJournal` revisit

A promotion writes an `EditJournal` row against the **target** `Page` row and
lets `commit_worker` push it. This is the right pathway — but the journal was
designed before placeholders existed, and that shows:

**`base_revid=None` currently carries two different meanings.** `commit_worker`
infers "this is a creation" from `journal.base_revid is None and page.revid is
None`. That is the same overloading as §3.2, and it is *why* `createonly` cannot
currently be set correctly: the push path infers intent instead of being told it.

- [ ] Record the intent explicitly on the journal row (`create` vs `update`)
      rather than inferring it from two nullable columns. This is a prerequisite
      for §5.6, and it is worth doing for ordinary IDE saves too.
- [ ] Add provenance:

```python
class EditSource(str, Enum):
    ide = "ide"
    promotion = "promotion"

# EditJournal gains:
source: EditSource = Field(default=EditSource.ide, index=True)
intent: EditIntent                      # create | update — no longer inferred
source_page_pk: int | None = Field(default=None, foreign_key="page.pk")
source_revid: int | None = None
base_rung: BaseRung                     # recorded | discovered | patch | none
batch_pk: int | None = Field(default=None, foreign_key="promotionbatch.pk", index=True)
```

- [ ] Mirror `batch_pk` onto `Commit` so a batch's outcomes are one query and
      rollback has an exact `(page, result_revid)` list.
- [ ] Keep `GET /commits/pending` shape unchanged for the IDE case; filter by
      `source`.

### 5.4 Summaries and attribution

- [ ] Honest, configurable summary template —
      `Proofread offline via wikisource-plugin (batch #123, from local staging copy)`.
      Transparency is the cheapest defence against the "opaque mass edit"
      objection.
- [ ] Set the bot flag only if the account actually has it. Using `bot` to hide
      edits from RecentChanges is precisely the optics failure to avoid.
- [ ] Respect `{{nobots}}` / `{{bots|deny=…}}`.
- [ ] Non-zero `put_throttle` and `maxlag` for the upstream site, **not** shared
      with the local site's settings.

### 5.5 Preflight

- [ ] Re-probe target heads; recompute state; recompute merges.
- [ ] Run checks/transforms, collect pass/warn/block, compute per-page and batch
      diff aggregates.
- [ ] **No-op detection** — drop pages whose transformed body already matches the
      target head.
- [ ] **Dry run against a non-public target** as a first-class option. Cheap once
      the target site is a parameter, and the highest-value safety feature here —
      the docker ProofreadPage instance (§9) is the natural sink.

### 5.6 Atomic preconditions

The answer to "the remote may have been edited or created in parallel and we
cannot track creation": **don't track it — make the push conditional and let the
server enforce it.** The database is a *plan*; the wiki is the authority on
whether the plan still holds at execution time. This is what makes probe
staleness tolerable rather than fatal, and it is why §8's TTL question mostly
dissolves.

None of these are currently used — `grep createonly src-py` returns nothing:

- [ ] **`createonly=1` on every create.** Today `save_page` treats
      `base_revid=None` as creation and calls `page.save()` with no guard, so a
      page created on the target since our probe is **silently overwritten**.
      Requires §5.3's explicit intent to set correctly.
- [ ] **`nocreate=1` on every update** — don't silently resurrect a page deleted
      since we looked.
- [ ] **`basetimestamp` + `starttimestamp`** matching the revision we actually
      based on. `PywikibotClient.save_page` currently reads
      `page.latest_revision.revid`, compares in Python, then saves — a TOCTOU
      window, after which pywikibot enforces "unchanged since I loaded it 200 ms
      ago" rather than "unchanged since `base_revid`".
- [ ] Verify these thread through `Page.save()`; if not, use `site.editpage()` or
      a raw request. Do not settle for the client-side check.
- [ ] Map API error codes (`articleexists`, `missingtitle`, `editconflict`,
      `protectedpage`, `abusefilter-*`, `spamblacklist`) to distinct `Commit`
      outcomes. Everything non-`EditConflict` currently collapses into
      `CommitStatus.error` with a stringified exception — too coarse to drive a
      retry or a UI decision.
- [ ] `force=True` means "drop the revid precondition" only — never
      `createonly`/`nocreate`.

### 5.7 A rejected push is a merge trigger

**Never retry harder — reclassify.**

- [ ] `articleexists` on a create → fetch the now-existing target page,
      reclassify as diverged with an empty base (§4.4).
- [ ] `editconflict` on an update → refetch, re-merge against the recorded base.
- [ ] Use a real three-way merge (`merge3`, or shell out to `git merge-file`).
- [ ] **ProofreadPage-specific win:** a `Page:` body decomposes into
      `<noinclude>` header / body / `<noinclude>` footer. Merge the three
      segments *independently*. Most cross-wiki conflicts are header-only
      (`pagequality` level and user) where resolution is deterministic — take the
      higher level, take the target's user attribution — so segmenting converts a
      large fraction of "conflict" into "clean merge" and leaves genuine prose
      conflicts standing out.
- [ ] Auto-merged results still require human review. A clean merge lowers review
      effort; it does not grant approval.

---

## 6. Batching, rollback, guardrails

### 6.1 Model

```python
class PromotionBatchStatus(str, Enum):
    draft = "draft"; preflight = "preflight"; approved = "approved"
    running = "running"; complete = "complete"; partial = "partial"
    aborted = "aborted"; rolled_back = "rolled_back"

class PromotionBatch(SQLModel, table=True):
    pk: int | None = Field(default=None, primary_key=True)
    source_site_pk: int = Field(foreign_key="site.pk")
    target_site_pk: int = Field(foreign_key="site.pk")
    index_page_pk: int | None = Field(default=None, foreign_key="page.pk")
    label: str
    comment_template: str
    status: PromotionBatchStatus = PromotionBatchStatus.draft
    created_at: datetime = Field(default_factory=utcnow)
    approved_at: datetime | None = None
    approved_by: str | None = None
```

- [ ] Add `PromotionItem` to hold the pairing and preflight result — check
      outcomes, base rung, diff stats, and the **pre-push target revid**, which
      is what rollback targets and therefore must be persisted.

### 6.2 Rollback

- [ ] Per page: restore `PromotionItem.pre_push_revid` via `undo`/`undoafter`
      rather than pushing a recorded body, so it registers as a proper revert in
      history.
- [ ] **Refuse to roll back blind.** If the target head is no longer our
      `result_revid`, someone edited on top; surface it and require manual
      handling.
- [ ] Batch rollback is itself a batch — same machinery, same audit trail.
      Report partial results honestly ("reverted 380 of 400; 20 have subsequent
      edits by others").

### 6.3 Guardrails

- [ ] Hard cap per batch (~50), overridable with typed confirmation.
- [ ] Server-side rate limit per target site, enforced in the worker.
- [ ] `POST /promotions/{pk}/abort` — a flag check in the already-serialised
      per-page loop.
- [ ] `Site.is_public` marking, driving the extra confirmation and the loud UI
      treatment. The local wiki stays frictionless.
- [ ] Minimal-grant BotPassword for upstream (edit; not delete, not protect).
- [ ] **Illustration upload is tractable and worth scoping in.** Inline images
      created during transcription (e.g. Tractatus diagrams) are own work with
      clear licensing, and small. Uploading those as part of a batch removes the
      §5.2 redlink block for the common case. Scan (PDF/DjVu) upload is a
      separate, case-by-case decision and stays out of scope.

---

## 7. API surface (proposed)

```
POST   /links                          { local_page_pk, upstream:{family,code}, upstream_title }
POST   /links/propose                  { index_page_pk, upstream_site_pk } -> mappings + confidence
GET    /links/{local_page_pk}          -> link + three-way state + base rung
POST   /links/{local_page_pk}/refresh
POST   /links/{local_page_pk}/find-base   -> run the §4.2 history intersection
DELETE /links/{local_page_pk}

POST   /promotions                     { source_site_pk, target_site_pk, index_page_pk | page_pks[], label }
POST   /promotions/{pk}/preflight      -> per-item checks + batch aggregates
GET    /promotions/{pk}                -> batch + items
GET    /promotions/{pk}/items/{item}   -> full three-way diff payload
PATCH  /promotions/{pk}/items/{item}   { included: bool, body_override?: str }
POST   /promotions/{pk}/approve        { confirm_page_count: int }
POST   /promotions/{pk}/run
POST   /promotions/{pk}/abort
POST   /promotions/{pk}/rollback
```

- [ ] The echoed `confirm_page_count` is deliberate friction — keep it.
- [ ] `run` must be resumable and idempotent per item.
- [ ] `PATCH …/items/{item}` with `body_override` is the seam that lets *either*
      the viewer or IntelliJ resolve a conflict (§8.5).

---

## 8. Viewer (Svelte) UI

Under `viewer/src/routes/promotions/`, reusing `DiffView`, `ActionButton`,
`Notice`, `PageHeading`, `StagedPageCard` and the existing `commits/` visual
language. The `commits/` routes stay as they are — IDE-originated staged edits
are a different thing.

| Route | Purpose |
|---|---|
| `/promotions` | batch list + quick rollback |
| `/promotions/new` | assemble: source site, target site, Index or page list |
| `/promotions/[pk]` | the review screen |
| `/promotions/[pk]/[item_pk]` | three-way diff for one page |
| `/links` | correspondences: proposed / confirmed / base rung |

### 8.1 Review screen

The non-obvious parts:

- **Target banner.** Full-width, red/amber against the warm parchment palette,
  naming the host: *"Target: en.wikisource.org — public wiki. 42 pages will be
  edited."* The single most valuable pixel in this feature is the one that stops
  someone approving against the wrong site.
- **Include-checkbox defaults carry the policy**: `local_ahead` with no blocks →
  checked; everything else → unchecked; blocked → disabled. The safe batch is
  the one you get by not thinking.
- **Base rung per row**, not just state. A rung-3 patch merge and a rung-1 clean
  push should not look identical.
- **Preflight freshness** shown with the timestamp, and approve disabled when
  stale or when any included item has a blocking check.
- **Approve states the consequence in words** — *"Push 38 edits to
  en.wikisource.org as `Username`, ~1 edit / 6 s, ≈4 minutes"* — and requires the
  echoed page count.
- Rollback stays available on the batch page forever.

### 8.2 Three-way diff

- Two diffs side by side: `base → local` (what we did) and `base → target head`
  (what they did). For `local_ahead` the second is empty; for `diverged` this is
  the entire point of the screen.
- The **transform chain as steps** — raw local body → after each transform →
  final submitted body. Reviewers need to see what the tool changed, not only
  what they wrote.
- Body-override editor for in-place conflict resolution.
- `buildLineDiff` (`viewer/src/lib/diff.ts`) is line-based; word-level intra-line
  diff would help here. Later.

### 8.3 Links screen

- Correspondences by work, with base rung and last probe.
- Title-match proposal flow: side-by-side titles, confidence, confirm/reject,
  confirm-all for an index once the scan-sha1 check passes.
- Loud display of the scan-file comparison — same / different / offset applied.
  This is where the offset bug gets caught.

### 8.4 Division of labour with IntelliJ

Review and approval stay in the viewer — iteration speed on the IntelliJ SDK is
much worse, and triaging 40 diffs is a web-shaped task. But **conflict
resolution is IDE-shaped**: IntelliJ has a real three-way merge UI and
PSI-level wikitext support, and nothing reasonable built in Svelte will match
it. Split by task rather than by feature:

- [ ] Viewer: triage, batch assembly, approval, rollback.
- [ ] IntelliJ (later): open a `diverged` item in the platform merge tool, write
      the result back through `PATCH …/items/{item}` — the same seam the viewer's
      override editor uses.
- [ ] IntelliJ (later): link-state decoration in the tool window; "Promote this
      page…" creating a single-page batch.

---

## 9. Phasing

**Phase 0 — parallel model (§3).** `Existence` tri-state + `remote_checked_at`;
`probe_pages`; materialize a target work via the existing fan-out; pairing as a
persisted outer join. No writes, no UI. Independently verifiable against Hertz:
the output is just "here is the join, here is what we know and don't know".

**Phase 1 — base discovery (§4).** `RemoteLink` + `find-base`; the normalized-hash
history intersection; local-side base extraction for patch mode. **Prototype
rung 2 against Hertz before building anything on top of it** — if normalized
matching finds the fork point there, title-matched links become nearly as good
as cloned ones, and that determines how much of §4.3 carries the load.

**Phase 2 — single-page promotion.** Explicit journal intent + `createonly` /
`nocreate` / `basetimestamp` + error-code mapping (§5.6, §5.3) — worth doing
independently of sync, since the silent-overwrite-on-create gap exists today.
Then `EditSource`, the check/transform framework, and a single-page promote
reviewed in the viewer. Target the docker wiki first, then one real Hertz page.

**Phase 3 — batches.** `PromotionBatch` / `PromotionItem`, preflight, approve,
run, abort, throttle, caps.

**Phase 4 — rollback.** `undo`-based per-item revert with the head-is-still-ours
check; batch rollback as a reverse batch.

**Phase 5 — divergence at scale.** Segment-wise merge, override editor, IntelliJ
merge-tool integration.

Do not start Phase 3 before Phase 4 is designed — mass commit without mass
revert is the exact shape of the risk this document exists to manage.

---

## 10. Testing

The new `docker-compose.yml` ProofreadPage instance changes what is possible
here: **two instances give a complete offline two-wiki fixture**, which is
exactly what this feature needs and what `FakeWikiClient` cannot simulate
(revision history, sha1 semantics, `createonly`, `undo`).

- [ ] Stand up a second instance as the "upstream" and build a real diverged
      fixture: create a page, copy it across, edit both sides, then assert the
      §4.2 intersection finds the right base.
- [ ] Pin the sha1 encoding trap in both directions (done — `test_wiki_sha1.py`)
      and the proofread-page stored-hash discrepancy (done —
      `test_proofread_serialization.py`, which runs without Docker).
- [ ] `FakeWikiClient` for the fast unit-level pipeline tests (states, checks,
      transforms, batch bookkeeping).
- [ ] Two sites with differing `File:` sha1s must refuse to link children.
- [ ] A batch targeting an `is_public` site must not run without an approval
      record.
- [ ] Use the docker instance as the dry-run sink for the whole batch path before
      anything points at en.wikisource.

---

## 11. Open questions

1. **Scan (PDF/DjVu) upload — case by case.** Inline transcription illustrations
   are own work and scoped in (§6.3); backing scans carry provenance and
   licensing decisions that differ per work, and per target (Commons vs local).
   Deferred pending a real case.
2. **Per-page or per-work approval for routine work?** Per-work approval of clean
   `local_ahead` pages is the ergonomic goal once trust is established. Start
   strict, loosen with evidence.
3. **Protected / semi-protected target pages** — detect and surface; probably
   block.
4. **How far back to walk history in §4.2?** `rvlimit=max` is 500 for anonymous
   requests. Almost certainly enough per page, but an Index page on a busy work
   could exceed it, and the fork point is likely to be *old* — i.e. exactly the
   end that gets truncated. Needs a paged walk or a bounded-search heuristic.
5. **Does patch mode (§4.3) want the local journal replayed per-save, or squashed
   to one delta?** Squashed is simpler and matches "one wiki edit per page".
   Per-save would preserve intermediate structure but has no obvious consumer.
   Squash unless a case appears.
