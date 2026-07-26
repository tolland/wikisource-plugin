# Upstream sync — promoting local proofreading to en.wikisource.org

**Status: design / TODO. Nothing here is built yet.**

This document works out the process for taking work done on the local staging
wiki (`https://wikisource-debian-13.lan`) and pushing it back to the canonical
upstream wiki (`https://en.wikisource.org`), page by page or a whole work at a
time.

Concrete motivating case:

| | |
|---|---|
| local | `https://wikisource-debian-13.lan/wiki/Page:The_principles_of_mechanics_presented_in_a_new_form_(Hertz,_1894).pdf/101` |
| upstream | `https://en.wikisource.org/wiki/Page:The_principles_of_mechanics_presented_in_a_new_form_(Hertz,_1894).pdf/101` |

Related reading: `src-py/DESIGN.md` §9 (cross-wiki correspondence, the
`RemoteLink` sketch) and §4.3 (commit API). This document is the operational
follow-on to §9 — §9 says *what the link object looks like*, this says *what the
promotion pipeline does with it and what the UI is*.

---

## 1. What we already have

The push-back half of the problem is solved, for a single site:

- `EditJournal` (`src-py/wtbot/model/edit_journal.py`) — append-only local log of
  saves. A VFS write never touches the wiki; it appends a row and flips
  `Page.dirty`.
- `Commit` (`src-py/wtbot/model/commit.py`) — outbound log, one row per push
  attempt, with `base_revid`, `submitted_body`, `status`, `result_revid`,
  `error_message`.
- `commit_worker.py` — claims a page's uncommitted journal batch, snapshots it
  out of the transaction, pushes the *latest* body via
  `WikiClient.save_page(title, text, base_revid, comment, force=)`, records the
  outcome, enqueues a refetch. Per-page granularity, `_worker_lock` serialises,
  `force=True` bypasses the `base_revid` conflict check.
- `api/commit.py` — `GET /commits/pending`, `POST /commits/`, `POST
  /commits/{page_pk}?force=`, `DELETE /commits/{page_pk}/pending`.
- Viewer review UI — `viewer/src/routes/commits/+page.svelte` (staged list) and
  `commits/[page_pk]/+page.svelte` (diff + approve / force / cancel), with
  reusable `DiffView`, `JournalList`, `StagedPageCard`, `ActionButton`,
  `Notice`.
- `Site` is already multi-instance by `(family, code)`, `SiteCredential` is
  per-site, and `Page` is keyed `(site_pk, title)` — so the same title on two
  wikis is already two distinct rows. Nothing needs restructuring for that.
- `Page.sha1` is already populated on every fetch — the cross-wiki "same
  content" oracle.

## 2. What is actually missing

Two things, and they are separable:

1. **Correspondence.** Which upstream page is "the same page" as this local one,
   and what revision did the local copy diverge from.
2. **A source of edits that isn't a human typing in IntelliJ.** Today an
   `EditJournal` row exists because someone saved a buffer. For promotion, the
   row's body has to be manufactured from *the corresponding page on the other
   site*.

Everything downstream of "an `EditJournal` row exists for the upstream `Page`
row" is already built. That is the key structural insight and it should shape
the implementation: **promotion is a producer of journal rows on the upstream
site's pages, not a second commit engine.**

## 3. Direction, and why this one is riskier

§9 of DESIGN.md is written mostly from the *pull* direction (upstream advanced,
fast-forward the local copy). This is the *push* direction, and it is
asymmetric:

- Pull is private and free — worst case we clobber our own staging wiki.
- Push is public, attributable, and to a community wiki with bot policies. The
  edits themselves are presumably fine (that's the point of proofreading
  locally). The risks are **volume, automation optics, and silent
  systematic error** — a normalisation bug replicated across 400 pages of a work
  is embarrassing in a way one bad edit is not, and it draws attention to
  automation that an observer can't inspect.
- It's recoverable — everything is revertible on en.wikisource. So the design
  goal isn't "never make a mistake", it's **"make every mistake bounded,
  visible, and undoable in one action"**.

Design consequences, and these should be treated as non-negotiable:

- Nothing is ever pushed upstream without an explicit human approval action for
  that specific batch.
- Batches are bounded and their size is stated up front, in the UI, before
  approval.
- Every promoted edit is traceable to a batch, and every batch has a one-click
  rollback.
- Preflight checks run before the human sees the approve button, and failures
  block by default rather than warn.

---

## 4. Correspondence model

### 4.1 The link object

Implement `RemoteLink` broadly as sketched in DESIGN.md §9
(`src-py/wtbot/model/remote_link.py`), with the additions promotion needs:

```python
class RemoteLink(SQLModel, table=True):
    """One local page's tracking relationship to the same logical object on
    another site — a git remote-tracking ref plus a recorded merge base."""
    __table_args__ = (
        UniqueConstraint("local_page_pk", "upstream_site_pk", name="uq_link"),
    )
    pk: int | None = Field(default=None, primary_key=True)

    local_page_pk: int = Field(foreign_key="page.pk", index=True)
    upstream_site_pk: int = Field(foreign_key="site.pk", index=True)
    upstream_title: str
    # NEW vs §9: the resolved upstream Page row, once fetched. Lets promotion
    # reuse the existing per-page commit path without a title lookup, and makes
    # "has the upstream side ever been fetched?" a FK check.
    upstream_page_pk: int | None = Field(default=None, foreign_key="page.pk")

    # merge base — the upstream revision we last reconciled against
    base_sha1: str | None = None
    base_revid: int | None = None
    base_body: str | None = None      # NEW: needed for real 3-way merge
    base_synced_at: datetime | None = None

    # last seen upstream head
    upstream_head_sha1: str | None = None
    upstream_head_revid: int | None = None
    upstream_checked_at: datetime | None = None

    origin: LinkOrigin = LinkOrigin.manual   # clone | title_match | manual
    confidence: float | None = None          # for title_match seeding
```

`base_body` is an addition to the §9 sketch. §9 gets away with hashes alone
because it only classifies state; an actual three-way merge (§6.4) needs the
base *text*, and re-fetching a historical revision from upstream at merge time
is both slow and possibly impossible (revision deletion). Store it.

### 4.2 Seeding links

Three mechanisms, in decreasing order of trustworthiness:

- [ ] **Clone.** The `wikictl clone --src wikisource:en --dest mywikisource:en
      --index Index:…` flow from §9. Correspondence is asserted at creation
      time, and `base_sha1` / `base_body` are exactly the upstream revision that
      was copied. This is the only path that gives a *correct* merge base for
      free, and it should be the recommended one.
- [ ] **Title match + confirm.** For works already staged locally by other means
      (the Hertz case, most likely). Normalise both titles (underscore/space,
      first-letter case, percent-decoding, namespace canonicalisation via each
      site's `Namespace` role map — do **not** compare numeric ns ids, they
      differ between installs) and propose links for review. The merge base is
      unknown; see §4.4.
- [ ] **Manual.** `POST /links` with an explicit pair, for renamed pages.

Never auto-link without a human confirming the mapping at least at the *work*
level. Title collision across two Wikisources is plausible enough (different
scans of the same edition) that silent matching is a bad default.

### 4.3 Work-level linking, not just page-level

Link at the `Index:` level and derive the `Page:` children:

- [ ] `RemoteLink` on the Index page.
- [ ] Children match by **page offset within the index**, not by parsing the
      subpage number out of the title. Use `list_index_pages`
      (`list=proofreadpagesinindex`) on both sides — it returns
      `(page_offset, title, pageid)` and is authoritative.
- [ ] **Critical check: the backing scan must be the same file.** Compare
      `FileMeta.file_sha1` of the `File:` on both sides. If the local wiki has a
      different upload of `The principles of mechanics….pdf` (re-derived DjVu,
      different page count, cropped cover), then local page 101 is **not**
      upstream page 101 and every promotion in the work is silently off by an
      offset. This is the single worst failure mode available here and it must
      be a hard block, not a warning. Where the files differ but page counts
      match, allow an explicit user-supplied constant offset with a spot-check
      confirmation UI (show local scan N and upstream scan N side by side).

### 4.4 When the merge base is unknown

Title-matched links have no honest `base_sha1`. Options, in order of preference:

1. If local `sha1` == upstream `sha1` right now, the pages are identical:
   adopt the upstream head as the base. Free and correct.
2. Walk upstream history (`revisions` API) for a revision whose `sha1` matches
   the local page's *earliest* known body. If found, that's the real fork point.
3. Otherwise mark the link `base_unknown` and force promotions on it through the
   **diverged** path — full manual diff review, no fast-forward, no bulk
   approval. Do not fabricate a base.

- [ ] Represent `base_unknown` explicitly rather than as `base_sha1 = None`
      overloading "never synced".

---

## 5. The promotion pipeline

### 5.1 State classification

Per linked page, compare three hashes — local body `sha1`, `base_sha1`, freshly
polled `upstream_head_sha1` — exactly the §9 table, read in the push direction:

| local vs base | upstream vs base | state | promotion action |
|---|---|---|---|
| same | same | `in_sync` | nothing to promote |
| changed | same | `local_ahead` | **promotable** — clean push |
| same | changed | `upstream_ahead` | nothing to promote; offer a pull |
| changed | changed | `diverged` | manual 3-way merge required |
| — | — | `upstream_missing` | promotion is a page *creation* |

`local_ahead` is the bulk-promotable case and the only one eligible for batch
auto-approval. Everything else requires per-page handling.

- [ ] Note that "local body" for this purpose must be the **effective** body —
      `PageStore.effective_body` semantics, i.e. bridge on an uncommitted local
      `Commit`/journal if the refetch hasn't landed. Promoting a stale cached
      snapshot while a newer local save sits in the journal would be a
      surprising, hard-to-spot bug.
- [ ] Decide: should promotion refuse while the *local* page has uncommitted
      journal rows? Recommendation: yes, block with a clear "commit locally
      first" message. Two pending-write concepts on one page is a UX trap.

### 5.2 Body transformation (the part that is not a byte copy)

The local body cannot generally be pushed verbatim. Each of these needs a
transform step with a visible before/after in the review UI:

- [ ] **`<pagequality>` header.** ProofreadPage stores quality level and the
      attributing user in the page content:
      `<noinclude><pagequality level="3" user="LocalUser" /></noinclude>`.
      Pushing that verbatim attributes the proofreading to a username that may
      not exist upstream. Rewrite `user=` to the upstream account performing the
      push.
- [ ] **Quality level policy.** Never promote a page *up* to level 4
      (Validated) — on Wikisource validation must be done by a different user
      than the proofreader, and asserting it via automation from a staging wiki
      is exactly the kind of thing that draws the wrong attention. Cap promoted
      levels at 3 (Proofread) by default, configurable, and **never downgrade**
      an upstream page's existing level.
- [ ] **Local-only templates and modules.** Scan the body for `{{…}}` /
      `{{#invoke:…}}` and check each exists upstream. A template that resolves
      locally but redlinks on en.wikisource produces visible breakage across
      every promoted page. Hard block on missing templates.
- [ ] **Local-only File: references.** `IndexMeta.short_name` generates names
      like `File:{short_name}_page_101_image_1.jpg` for extracted illustrations.
      Those files exist locally and do not exist upstream. Either block, or
      (later) make image upload part of the promotion batch.
- [ ] **Interwiki / absolute links to the staging host.** Any
      `wikisource-debian-13.lan` URL in the body is a hard block — leaking a LAN
      hostname into en.wikisource is both broken and mildly disclosive.
- [ ] **Categories** that exist locally but not upstream — warn, don't block.

Implement these as an ordered list of named `PromotionCheck` /
`PromotionTransform` objects (typed classes, per the project's Python style),
each returning `pass` / `warn` / `block` with a human-readable message and, for
transforms, the rewritten body. The UI renders that list per page. New rules are
then a class, not a change to the pipeline.

### 5.3 Execution

- [ ] A promotion writes an `EditJournal` row against the **upstream** `Page`
      row, with `base_revid` = upstream head revid at preflight time, body = the
      transformed body, comment = the generated edit summary.
- [ ] The existing `commit_worker` then pushes it. No second push engine.
- [ ] Add a provenance discriminator so the two kinds of pending edit are
      distinguishable everywhere they surface:

```python
class EditSource(str, Enum):
    ide = "ide"                # a human saved a buffer (today's only case)
    promotion = "promotion"    # manufactured from a corresponding page

# EditJournal gains:
source: EditSource = Field(default=EditSource.ide, index=True)
source_page_pk: int | None = Field(default=None, foreign_key="page.pk")
source_revid: int | None = None
batch_pk: int | None = Field(default=None, foreign_key="promotionbatch.pk", index=True)
```

- [ ] Mirror `batch_pk` onto `Commit` so a batch's outcomes are one query, and
      so rollback has an exact list of `(page, result_revid)` to undo.
- [ ] `GET /commits/pending` must keep working unchanged for the IDE case;
      filter by `source` rather than changing its default shape.

### 5.4 Edit summaries and attribution

- [ ] Summary template, configurable, defaulting to something honest and
      linkable, e.g.
      `Proofread offline via wikisource-plugin (batch #123, from local staging copy)`.
      Do not disguise the automation — a transparent summary is the cheapest
      possible defence against the "opaque mass edit" objection.
- [ ] Mark edits as bot edits only if the account actually has the bot flag;
      otherwise leave them visible in RecentChanges. Flagging unflagged edits as
      `bot` to hide them from RC is precisely the optics failure to avoid.
- [ ] **Licensing/attribution**: if the local body originated upstream (the
      clone case), pushing derived text back is fine. If text was authored
      locally by other contributors, the summary should attribute them.
- [ ] Respect `{{nobots}}` / `{{bots|deny=…}}` on the target page.
- [ ] Set `maxlag` and throttle. pywikibot handles this if configured; verify
      `put_throttle` is non-zero for the upstream site and **not** shared with
      the local site's settings (local pushes should stay fast).

### 5.5 Preflight, and the dry run

Before any human sees an approve button for a batch:

- [ ] Re-poll upstream heads for every page in the batch (cheap
      `prop=revisions&rvprop=ids|sha1` bulk query, not a full fetch).
- [ ] Recompute state per §5.1; anything not `local_ahead` /`upstream_missing`
      drops out of the auto-approvable set.
- [ ] Run all checks/transforms; collect pass/warn/block.
- [ ] Compute the diff and stats per page, plus batch aggregates: pages,
      total ± lines, largest single diff, count of pages whose diff exceeds a
      threshold.
- [ ] **No-op detection**: if the transformed body hashes equal to the upstream
      head body, drop the page from the batch. Null edits are noise.
- [ ] Offer a **dry-run against the local wiki** (or a third scratch wiki) as a
      first-class option: run the whole batch against a target that isn't
      en.wikisource and inspect the result. Cheap to build once the target site
      is a parameter, and it's the highest-value safety feature here.

---

## 6. Batching, rollback, and the safety envelope

### 6.1 `PromotionBatch`

```python
class PromotionBatchStatus(str, Enum):
    draft = "draft"           # assembled, preflight not run
    preflight = "preflight"   # checks run, awaiting approval
    approved = "approved"
    running = "running"
    complete = "complete"     # all pages terminal
    partial = "partial"       # some succeeded, some failed
    aborted = "aborted"
    rolled_back = "rolled_back"

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

Per-page membership can live on the manufactured `EditJournal` rows via
`batch_pk` rather than needing a separate join table — but a `PromotionItem` row
is worth it anyway to hold the *preflight result* (check outcomes, computed
diff stats, pre-push upstream revid) without recomputing.

- [ ] Decide: `PromotionItem` table vs. recompute. Recommendation: add it. The
      pre-push upstream revid in particular **must** be persisted — it's what
      rollback targets.

### 6.2 Rollback

- [ ] **Per page.** Restore the upstream revision that preceded our push
      (`PromotionItem.pre_push_revid`). Prefer MediaWiki's `action=edit&undo=` /
      `undoafter=` or `action=edit&oldid=`-style restore over pushing a
      recorded body — the wiki then computes the revert and it shows up as a
      proper revert in history.
- [ ] **Refuse to roll back blind.** If the upstream head is no longer *our*
      `result_revid`, someone edited on top of our change. Do not clobber them.
      Surface the intervening edits and require explicit manual handling.
- [ ] **Batch rollback.** Reverse order, same per-page rules, same throttle,
      with a progress view and the ability to stop. Report partial results
      honestly: "reverted 380 of 400; 20 have subsequent edits by others".
- [ ] Rollback edits get their own summary template referencing the batch.
- [ ] Rollback is itself a batch — reuse the same machinery and the same
      audit trail rather than making it a special case.

### 6.3 Guardrails to build

- [ ] **Hard cap** on pages per batch (default ~50), overridable with an
      explicit typed confirmation.
- [ ] **Rate limit** across batches (e.g. N edits/minute, M/day to a given
      site), enforced server-side in the worker, not in the UI.
- [ ] **Kill switch.** `POST /promotions/{batch}/abort` that stops the worker
      between pages. The worker is already per-page and serialised, so this is
      a flag check in the loop.
- [ ] **Target-site marking.** A `Site.is_public` / `Site.protection_level`
      flag. Everything targeting a public site gets extra confirmation and loud
      UI treatment; the local wiki stays frictionless.
- [ ] **Separate credentials** for upstream, with a distinct BotPassword whose
      grants are minimal (edit existing pages; not delete, not protect).
      `SiteCredential` already supports this per site.
- [ ] Consider requiring the upstream account to have made some manual edits
      first — a brand-new account mass-editing is the fastest route to a block.

---

## 7. API surface (proposed)

Links:

```
POST   /links                       { local_page_pk|local_title, upstream:{family,code}, upstream_title }
POST   /links/propose               { index_page_pk, upstream_site_pk } -> proposed mappings + confidence
GET    /links/{local_page_pk}       -> link + three-way state
POST   /links/{local_page_pk}/refresh
DELETE /links/{local_page_pk}
```

Promotions:

```
POST   /promotions                     { source_site_pk, target_site_pk, index_page_pk | page_pks[], label }  -> batch (draft)
POST   /promotions/{pk}/preflight      -> per-item check results + batch aggregates
GET    /promotions/{pk}                -> batch + items (state, checks, diff stats)
GET    /promotions/{pk}/items/{item}   -> full three-way diff payload
PATCH  /promotions/{pk}/items/{item}   { included: bool, body_override?: str }
POST   /promotions/{pk}/approve        { confirm_page_count: int }   # count must match, no fat-fingering
POST   /promotions/{pk}/run            -> drains via commit_worker
POST   /promotions/{pk}/abort
POST   /promotions/{pk}/rollback       -> creates and runs a rollback batch
```

- [ ] `approve` taking an echoed page count is a deliberate friction point —
      keep it.
- [ ] `run` should be resumable and idempotent per item.

---

## 8. Viewer (Svelte) UI

Build under `viewer/src/routes/promotions/`, reusing the existing components
(`DiffView`, `ActionButton`, `Notice`, `PageHeading`, `StagedPageCard`) and the
existing visual language from `commits/`. The existing `commits/` routes stay as
they are — IDE-originated staged edits are a different thing and shouldn't be
merged into this view.

### 8.1 Routes

| Route | Purpose |
|---|---|
| `/promotions` | batch list: label, source→target, page count, status, created/approved, quick rollback |
| `/promotions/new` | assemble a batch: pick source site, target site, Index (or explicit page list) |
| `/promotions/[pk]` | the review screen — the heart of this feature |
| `/promotions/[pk]/[item_pk]` | full-page three-way diff for one page |
| `/links` | link management: proposed / confirmed / broken correspondences |

### 8.2 The review screen (`/promotions/[pk]`)

Top: a **target banner**. When the target site is public, this is unmissable —
full-width, distinct colour from the site's warm parchment palette (red/amber),
naming the target host explicitly: *"Target: en.wikisource.org — public wiki.
42 pages will be edited."* The single most valuable pixel in this feature is
the one that stops someone approving against the wrong site.

Then a **batch summary bar**: pages by state (`local_ahead` 38, `diverged` 3,
`in_sync` 1), aggregate +/− lines, blocking-check count, and the preflight
timestamp with a "re-run preflight" button (results go stale as upstream moves).

Then a **per-page table**, one row per item:

- include checkbox (defaults: `local_ahead` with no blocks → checked;
  everything else → unchecked and, for blocked items, disabled)
- page title, linked out to both the local and upstream URLs (open in new tab —
  reviewers *will* want to look at the real page)
- state chip (`local_ahead` / `diverged` / `upstream_ahead` / `in_sync`)
- diff stat `+12 / −3`
- check chips: green/amber/red counts, with the failing check names on hover
- inline expand → `DiffView` right there, no navigation
- link to the full three-way view

Bulk controls: select all / none / all-clean, "exclude everything with a
warning", and a filter by state.

Footer: **approve**. Disabled until preflight is fresh and no *included* item
has a blocking check. Requires typing the page count (matching the API's
`confirm_page_count`). Shows exactly what will happen in words: *"Push 38 edits
to en.wikisource.org as `Username`, ~1 edit / 6s, ≈4 minutes."*

While running: progress bar, live per-row status, prominent **stop** button.
On completion: outcome summary and a **roll back this batch** button that stays
available on the batch page forever.

### 8.3 Three-way diff view (`/promotions/[pk]/[item_pk]`)

- Three columns / two diffs: `base → local` (what we did) and
  `base → upstream head` (what they did). For `local_ahead` the second is
  empty; for `diverged` this is the whole point of the screen.
- A **body override** editor for manual merge, saved via `PATCH …/items/{item}`,
  so a diverged page can be resolved in place without leaving the batch.
- The transform chain rendered as steps: raw local body → after pagequality
  rewrite → after each transform → final submitted body. Reviewers need to see
  what the tool changed, not just what they wrote.
- `buildLineDiff` in `viewer/src/lib/diff.ts` is line-based; for these bodies
  a word-level intra-line diff would help. Optional, later.

### 8.4 Links screen (`/links`)

- Table of correspondences by work, with state, base revision, last upstream
  poll.
- The **proposal flow** for title-matched links: side-by-side local/upstream
  titles with a confidence indicator, confirm/reject per row, confirm-all for an
  index once the scan-sha1 check has passed.
- Loud display of the scan-file comparison result for the work — same file /
  different file / offset applied. This is where the offset bug gets caught.

### 8.5 IntelliJ side

Out of scope for the first pass — the viewer is the right place for a
review-and-approve workflow with big diffs. Later, worth having in the plugin:

- [ ] Tool-window decoration showing a page's link state against upstream.
- [ ] "Promote this page…" action that creates a single-page batch and opens
      the viewer at it.
- [ ] Use IntelliJ's real diff/merge UI for the diverged case — it's better than
      anything reasonable to build in Svelte, and the PSI-level wikitext support
      is already there.

---

## 9. Phasing

**Phase 1 — correspondence only, no pushing.**
- [ ] `RemoteLink` model + migration.
- [ ] `POST /links`, `GET /links/{pk}`, refresh endpoint.
- [ ] Title-match proposal + scan-file sha1 comparison.
- [ ] `/links` viewer screen.
- [ ] Three-way state classification, read-only, surfaced in the UI.

Useful on its own — "which of my 400 local pages differ from upstream, and how"
is already worth having with no write path at all.

**Phase 2 — single-page promotion.**
- [ ] `EditSource` discriminator on `EditJournal` + `Commit.batch_pk`.
- [ ] Check/transform framework with the §5.2 rules.
- [ ] Single-page promote → manufactured journal row → existing commit path.
- [ ] Review UI for one page. Exercise it against the local wiki as target
      first, then one real Hertz page upstream.

**Phase 3 — batches.**
- [ ] `PromotionBatch` / `PromotionItem`, preflight, approve, run, abort.
- [ ] Batch review screen with bulk selection.
- [ ] Throttle + caps + rate limiting.

**Phase 4 — rollback.**
- [ ] Per-item revert via `undo`/`undoafter` with the "head is still ours" check.
- [ ] Batch rollback as a reverse batch.

**Phase 5 — divergence handling.**
- [ ] 3-way merge, body override editor, rebase-of-local-journal.

Do not start Phase 3 before Phase 4 is designed — a mass-commit feature without
a mass-revert feature is the exact shape of the risk this document exists to
manage. (Building 4 before 3 is fine and arguably better.)

---

## 10. Testing

- [ ] `FakeWikiClient` already supports two independent in-memory sites; the
      whole promotion pipeline should be testable with no network — including
      conflict, divergence, and rollback paths.
- [ ] vcrpy cassettes against the *local* wiki for the pywikibot-level calls
      (`proofreadpagesinindex`, bulk `rvprop=ids|sha1`, `undo`).
- [ ] Explicit test for the scan-offset failure: two sites whose `File:` sha1s
      differ must refuse to link children.
- [ ] Explicit test that a batch targeting a public site cannot run without
      an approval record.
- [ ] End-to-end against the local wiki as *both* source and target (a scratch
      namespace) before ever pointing at en.wikisource.

---

## 11. Open questions

1. **Where does the human actually review — viewer or IDE?** This doc assumes
   the viewer, on the grounds that reviewing 40 diffs is a web-shaped task.
   That elevates the viewer from "debug UI" to a real surface, which is a
   deliberate change of its status and worth confirming.
2. **Is `EditJournal` the right vehicle for promoted bodies?** Reusing it buys
   the entire commit path for free. It also puts synthetic rows in what is
   documented as a log of IDE saves. The alternative — a parallel
   `PromotionItem` → `Commit` path — duplicates the conflict/refetch logic that
   was hard to get right. Recommendation: reuse, with the `source` discriminator
   and updated docstrings.
3. **How is the merge base recovered for the Hertz work**, which is already
   staged locally without a clone record? Probably §4.4 option 2 (sha1 walk of
   upstream history). Worth prototyping early — if it works, title-matched links
   become nearly as good as cloned ones.
4. **Do we upload images?** Illustrations extracted locally have no upstream
   counterpart. Blocking is correct for now; file upload is a much larger
   surface (licensing, Commons vs local) and should stay out of scope.
5. **Per-page or per-work approval granularity for routine work?** Once trust
   is established, per-work approval of clean `local_ahead` pages is the
   ergonomic goal. Start strict; loosen with evidence.
6. **Should promotion be available at all while the upstream page is
   protected/semi-protected?** Detect and surface it; probably block.
