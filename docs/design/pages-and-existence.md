# Pages, existence, and the nullables that follow from it

Status: **in progress — step 1 landed; step 2 under way.** It records why
`PromotionBatch` is hard to read, why the reason is not where it looks, and
the model change that removes the cause rather than the symptom.

## 0. How it is being done, and what changed since this was written

The sections below were written for a single big change. That was tried
(branch `claude/confident-feynman-5p3l85`, kept for reference) and replaced by
a progressive route, because every step then ships and migrates on its own.

**The route: a shared primary key.** `page.pk` is a foreign key to `title.pk`.
Every existing page got a title *with the same pk*, so every foreign key that
points at `page.pk` already holds a valid `title.pk`. Moving a table over is a
change of constraint, never of data.

1. **Done.** Add `Title` (`site_pk`, `title`, `expected_content_model`), copy
   every page into it with the same pk, make `page.pk` reference it
   (migration `5d2a7c41e9b3`). The fan-out, `ensure_index_page` and the fetch
   worker create the Title first, with their own guess; a `before_flush` hook
   on `Page` covers everything else during the transition.
2. **Under way, a few tables at a time.** Repoint the foreign keys that are
   about an *address* from `page.pk` to `title.pk`, renaming the column to say
   so. No data moves: every `page_pk` value already is the right `title_pk`.
   - **Done** (`8e3f1b6d0a27`): `EditJournal.title_pk`, `Commit.title_pk`,
     `ProofreadPageMeta.title_pk` and `.index_title_pk`. A save, a push, and
     the scan/number/proposed body of an untranscribed page now need no Page
     behind them.
   - **Done** (`b41d8e2c7f60`): `PromotionBatch` reduced to its two ends,
     `source_page_pk` (a Page -- nothing to promote from a page the source
     wiki lacks) and `target_title_pk` (an address, never null). Sites,
     titles, correspondence, work and page number are resolved from those
     two (`promotion_store.batch_ends`); `source_head_revid` and
     `anchor_link_pk` stay as the freeze. Resolving the target's title at
     push time also fixed the redirect hazard of writing to a frozen name.
   - **Done** (`d7a3c9e5b184`): `IndexLink` shares `PageLink`'s primary key
     (every work *is* a pairing), and `PageLink.index_link_pk` is gone: a
     work's page pairs are derived from each page's
     `ProofreadPageMeta.index_title_pk` plus the other side's site
     (`index_link_store.children_of`). That removed the `indexlink` <->
     `pagelink` foreign-key cycle.
   - **Done** (`e5f2a8d1c349`): `ScanAnnotation`, `BoxRangeLink`,
     `TextTargetAnchor` keyed to `title_pk`: the scan exists before the page.
   - **Done** (`f8c0a6e2d493`): `Transclusion` and `FileMeta` dropped for
     redesign rather than moved; their shapes are in §12.
   - **Done** (`a9d4b7e1f026`): `IndexMeta` shares its Index's title key (so
     an Index assembled from the client carries its metadata before any wiki
     holds it), and `PageLink.local_page_pk`/`remote_page_pk` reference
     `title` -- a pairing is the intention to keep two addresses in step,
     whichever exists yet. The column names stay until the directed-links
     rework.
   - **Decided, staying on `page`:** `Revision` (a revision is of a page the
     wiki holds; deleted-and-recreated pages are out of scope), `FileBlob`
     (a blob is bytes the wiki holds; what a prospective blob would be is
     undefined), and `PromotionBatch.source_page_pk` (by design).
   - **Deferred, to be revisited:** directed, mirrored `PageLink` and
     `RevisionLink` on titles -- one row per direction, the mirror enforced
     by a deferred composite foreign key, removing the two expression
     indexes and the either-way lookups. It also fixes `sync.py`'s anchor
     report, which reads a rung's `local` as the sync's source. **Decided:
     a tracked work is per direction** -- an `IndexLink` will share the key
     of one directed pairing.
   - **Next:** the columns that belong to the address (`namespace_key`,
     `dirty`, `fetch_status`, `history_complete_from_revid`).

   Two things learned doing the first batch, and a third since. Tables whose
   constraints are not conventionally named, or which carry an expression
   index batch mode cannot reflect (`uq_pagelink_pair`), are rebuilt by
   SQLite's own procedure -- final DDL stated, rows copied, drop, rename --
   because batch mode would fail on the names or silently drop the index.

   The first two: Alembic's batch mode silently
   drops a foreign key or index created on a column renamed in the same
   batch -- the table rebuilds, every row survives, the constraint is gone,
   and `foreign_key_check` still passes because there is nothing to check.
   So the rename is SQLite's native `RENAME COLUMN`, the constraint swap a
   separate batch, and `test_the_migrated_schema_matches_the_models` now
   compares the migrated schema with the models on every run. And renamed
   columns reach old dumps: `restore` upgrades a dump through each schema
   step in turn (`_LEGACY_UPGRADES`).
3. **Last.** Delete `page` rows for titles the wiki holds nothing at, make the
   remaining columns NOT NULL, rename `page` to `wikipage`, drop the hook and
   `page.title`. The only step that removes data.

**What changed from the text below:**

- **The name is `Title`,** MediaWiki's own, as below. `TitlePage` was
  considered and dropped: in Wikisource a title page is a leaf of a book.
- **Namespace roles are gone** (`c38d2e7f901a`), so the `namespace_role`
  columns in §4 no longer exist. `namespace_key` identifies an address's
  namespace and belongs on `Title`.
- **`content_model` lives on both sides, under different names** — a
  refinement of §4. `Title.expected_content_model` is a guess, NOT NULL,
  needed before any fetch because the editor must open a title as something
  and `ProofreadPageMeta` hangs off what it is expected to be. It comes from
  context (fan-out, a file's extension, else `wikitext`), never from the
  namespace: `Index:Foo.pdf/styles.css` is in the Index namespace and is
  `sanitized-css`. `Page.content_model` (later `WikiPage.content_model`) is
  what the wiki said. The fetch compares them, logs a wrong guess, and adopts
  the wiki's answer (`wtbot.title_store`).
- **Migrations now run with foreign keys off**, in one real transaction, with
  `PRAGMA foreign_key_check` before commit (`wtbot.db.migration_connection`).
  Without that, rebuilding a table other tables reference — which every step
  here does — was impossible, and DDL was never rolled back on failure.
- **Dump/restore understand the shared key.** A restored page takes its
  title's number, and a dump taken before `title` existed is upgraded on the
  way in with the same rule as the migration.

The motivating complaint, stated plainly: *the promotion/sync path is reliable
on top of existing pages, but it is littered with checks for pages that do not
exist yet, and reasoning about it is expensive.*

## 1. The symptom

`PromotionBatch` carries three nullable foreign keys:

```python
index_link_pk: int | None    # the tracked work, when the pair is tracked
page_link_pk: int | None     # "null only while creating the target"
target_page_pk: int | None
```

Only the first is honestly optional (a pairing outside any tracked work —
mainspace, `Portal:`, a page paired before its work was). The other two are
null in exactly one situation: the target page has no row.

The cost is not the columns. It is that every consumer downstream re-derives
the same fact defensively — `api/sync.py:460`, `:510`, `:871` each guard
`if batch.target_page_pk is not None` and return "no correspondence" or an
empty target body instead of an answer — and that `promotion_store.py` asserts
four invariants at runtime that the type system should have held:

```
# pragma: no cover - actionable implies a head
# pragma: no cover - a push verdict implies one
# pragma: no cover - a push verdict implies a ladder
# pragma: no cover - rungs is non-empty
```

Four unreachable `PromotionError` branches. That is the codebase stating, in
comments, that it knows these invariants hold and cannot say so in a signature.

## 2. Two legacies, and only one of them dissolves

It is tempting to treat all of this as accumulated over-caution. It is not one
thing; it is two, with different causes and different remedies. Conflating
them risks deleting the wrong safeguard.

**The SHA-1 legacy.** `docs/reference/proofread-page-sha1-discordance.md`
records that MediaWiki's reported hash for some historical `proofread-page`
revisions does not describe the text the API serves. Content matching was
therefore not trustworthy, and a great deal of policy grew to compensate:
`MatchOutcome`, `linkable`, "proposals are never auto-confirmed",
`LinkOrigin.reconciled`. For newly created pages and new revisions the hash is
reliable, so some of that policy is now over-built. See §10.

**The null legacy.** Staging operates on targets that have no row. Entirely
separate cause. Unaffected by SHA-1 being trustworthy now. This note is about
this one.

## 3. A page that "does not exist" is not nothing

This is the observation the rest of the design turns on.

Take `Page:Principles of Psychology (1890) v1.djvu/104`, which no one has
transcribed. MediaWiki still serves, for that title:

- a **default body** — the OCR text layer of leaf 104, already wrapped in the
  `<pagequality>` scaffold, which `action=edit&redlink=1` prefills into the
  textarea;
- a **reference scan** thumbnail at any requested width;
- its **page number** and its **index membership**.

All fetchable, all authoritative, all before anybody saves anything. That is
the ProofreadPage extension's contract, not a UI nicety.

So "does this page exist?" was the wrong question throughout. There are three
separable things, and the middle one has been homeless:

| | What it is | When it is there |
|---|---|---|
| The name | `(site, title, namespace_role)` — addressable | as soon as anyone can type it |
| The proposed content | default body, scan, page number, index membership | for any paginated page of an index whose file is uploaded |
| The saved revision | what `revid` names | only once somebody saved |

The proposed content exists *independently of* the saved revision. It also
exists for saved pages — it is merely superseded. It is not a degenerate case
of a revision; it is its own thing, and `ProofreadPageMeta.default_body`
already stores it correctly.

`_is_placeholder` is what the absence of this distinction costs:

```python
return head_revision(session, page) is None and page.fetch_status == FetchState.done
```

An `AND` across two objects — "no revision" is a fact about the page, "we
asked" is a fact about the query — which is why it needs a docstring longer
than itself.

## 4. The split

`Page` is already the identity table: of the seventeen foreign keys to
`page.pk`, sixteen want the name, not a page that exists —
`EditJournal`, `Commit`, `PageLink` (×2), `PromotionBatch` (×2),
`ProofreadPageMeta` (×2), `FileMeta` (×2), `IndexMeta`, `FileBlob`,
`Transclusion` and the three annotation tables. Only `Revision.page_pk` is
arguably about an existing page, and it too wants the name so that a
delete-and-recreate does not orphan history.

So `Page` needs no rename. It needs five columns removed:

```python
class Page(SQLModel, table=True):
    """A page we know about. May or may not be saved on the wiki."""
    pk: int | None = Field(default=None, primary_key=True)
    site_pk: int = Field(foreign_key="site.pk", index=True)
    title: str
    namespace_role: NsRole
    fetch_status: FetchState          # a fact about the query, stays here
    fetch_error: str | None


class WikiPage(SQLModel, table=True):
    """The wiki has this page. Row present iff it exists upstream."""
    page_pk: int = Field(foreign_key="page.pk", primary_key=True)
    pageid: int
    namespace_key: int
    content_model: str
    latest_revision_pk: int           # MediaWiki's page_latest
```

Every `WikiPage` column is non-null and meaningless for a page that does not
exist — which is why they belong in a row that only exists when it does.
Existence stops being a derived predicate and becomes **row presence**.

Three placement notes:

- `revid`, `remote_timestamp`, `contributor` and `comment` do **not** move to
  `WikiPage`. They are properties of a *revision*, and MediaWiki's own `page`
  table holds only `page_id` and `page_latest` while the rest lives in
  `revision`. Keeping both `revid` and `latest_revision_pk` would recreate the
  dual-writer denormalisation that `sync.py:715` already flags — and which is
  the reason `_is_placeholder` had to read through `head_revision` rather than
  trust `Page.revid`. `Page.text` goes the same way: bodies live in
  `Revision` + `Content`.
- `content_model` is a **page** fact, not a namespace fact: MediaWiki's
  `page_content_model` is per-page (namespace default only when null), and
  under MCR the model is per-slot on the content row — which this schema
  already reflects in `Content.content_model`. So the authoritative value is
  per slot; `WikiPage.content_model` mirrors `page_content_model`; and a page
  with no revision has no stored model at all.
- An unsaved page still needs a model for the editor and `dispatch.py` to pick
  a parser. That value is the **namespace default from siteinfo** — a
  prediction of what the main slot will be. It must be obtained through an
  explicitly named lookup (`default_content_model(site, namespace)`) and must
  not be written into the same column as a fetched one. A guess and a fact
  sharing a field, distinguishable only by remembering which path filled it,
  is the whole problem restated.

Everything goes through `MAIN_SLOT` today. The slot dimension is already in
the schema, so the single-slot assumption is a choice, not an oversight.

## 5. What each consumer actually asks

Neither consumer asks about existence. They ask different questions, and the
current model forces both through the same nullable columns.

**The VFS wants a body.** It always has one: the journal/commit/snapshot chain
when there is a revision, the proposed content when there is not. This is
already true in the code, but as a patch *above* the model —
`vfs/mediawiki.py:158` does `body = state.body or (default_body or "")`,
splicing the default in after `effective_state_from` has already resolved to
`""`. Promoting that into `EffectiveState` makes the rule one ordered list
instead of two, and removes "virtual page" as a concept the VFS has to hold:

```
latest uncommitted EditJournal row      (a local save)
> a successful Commit ahead of the snapshot   (pushed; refetch pending)
> the head revision's body
> the proposed content                  (default body; nothing saved yet)
```

**Sync wants a revision to anchor on.** A page with no revision has nothing to
compare and no base to replay onto. That is out of scope for sync — not
because it does not exist, but because **there is no revision**. Stating it
that way unifies two cases the current code separates: a page nobody saved,
and a page that exists but whose history we have not fetched
(`SyncVerdict.unknown`). From sync's point of view these are identical. They
differ only in the remedy — create, versus fetch — which belongs in the
refusal message, not in the verdict enum.

So the boundary type is named after what sync needs, not after a wiki fact it
does not care about: a page with at least one cached revision. Sync's
signature takes one; a page without revisions cannot be passed to it, so there
is no branch, because there is nothing to branch on.

`SyncVerdict` then loses three members:

| Member | Where it goes |
|---|---|
| `create` | a different entry point (§6) |
| `unknown` | the resolver refuses; never reaches a verdict |
| `source_missing` | structure reconciliation, not a comparison result |

Leaving `in_sync` / `push` / `behind` / `diverged` / `unlinked` — five members
that are all statements about two pages with revisions and the ladder between
them. `SyncPage` correspondingly loses `target_is_placeholder` and `linkable`,
and `source_title`, `target_title`, `source_revid`, `target_revid` all become
non-null.

One nullable cluster stays, honestly: `pair_pk`, `anchor_source_revid`,
`anchor_target_revid` are null **iff** `unlinked`. That is a real two-case sum
(`Linked` / `Unlinked`), small enough to be a `match` with two total arms.

**`_is_placeholder` survives only as presentation.** The tool window and the
viewer legitimately badge a page as not yet on the wiki. Presentation may be a
derived predicate; nothing branches on it for control flow. In particular
`EffectiveState.placeholder` must stop being read as one — it is `revid is
None`, which is precisely the inference `PromotionIntent`'s docstring forbids.

## 6. Creation is a different verb

A page created by promotion has **known provenance**. `LinkOrigin.copy` is the
enum's own strongest member: "the correspondence is a fact about how the
revision came to exist." No comparison, no hash, no human needed.

Yet today a create routes through `_page_report` → `compare_pages` →
`linkable` → `ACTIONABLE`, machinery built for pages whose correspondence had
to be *guessed*, and comes out the far side with null foreign keys. Splitting
**discovery pairing** from **created pairing** removes the ceremony and the
nulls in one move, and it is justified by provenance rather than by trusting
content matching more — so it stands independently of §2's SHA-1 argument.

It also fixes a small standing inaccuracy: `_pairing_for`
(`remote_link_store.py:137`) materialises a pairing for a `copy` rung using
`pair_pages`' default origin of `title_match`, whose docstring promises the
row "has been through a human". A pairing should inherit its rung's origin.

**The seam.** `PromotionBatch` is where both shapes meet: a create's target is
a page with no revision, an update's target has one. One table, with
`PromotionIntent` as the discriminant it already is — recorded at staging, not
inferred from `base_revid is None`. This is the one place the design can leak
back out, so the meeting should happen there and nowhere else.

Two further consequences for the batch:

- `target_page_pk` becomes non-null trivially: the name exists the moment
  someone can type it.
- `target_title` becomes derivable, and should be derived. It is currently
  frozen at staging and used by the worker as the write target
  (`promotion_worker.py`, `snapshot = (..., batch.target_title, ...)` →
  `save_page(title, ...)`). If the target is moved on the wiki between staging
  and push, the worker edits the **redirect left behind** rather than the moved
  page, silently forking the content. `PageLink` was built to survive renames
  by pointing at pks; the batch bypasses that by carrying a string.

The general rule for the other duplicated columns: **freeze what was reviewed,
resolve what identifies.** `source_head_revid`, `Promotion.body`, `base_revid`
and `pre_push_target_revid` are deliberate freezes and must stay — what was
reviewed is what is sent. `source_title` / `target_title` are denormalised
mirrors and should go. (`Page.sha1` was already removed on the same grounds.)

## 7. Nullable as a value, versus nullable as a missing state

Not every null here is a defect. The distinction worth writing down:

> A null is legitimate when it is a value the wiki itself also has no value
> for. It is not legitimate when it encodes "we have not done the work yet" —
> that is a state, and states get rows or tags.

| Field | Verdict |
|---|---|
| `Page.pageid` / `revid` / `remote_timestamp` / … | bad — one representation for two states (unfetched, absent) |
| `PromotionBatch.target_page_pk`, `page_link_pk` | bad — "not materialised yet" |
| `PromotionBatch.index_link_pk` | fine — a page genuinely outside any tracked work |
| `EditJournal` / `Commit` / `Promotion.base_revid` | fine as a value — MediaWiki's `baserevid` is optional and its absence means "create" |
| `EffectiveState.placeholder` | bad — an inference, not a tag |

`base_revid` needs no removal. It needs the same explicit intent tag
`Promotion` already has, added to `EditJournal` and `Commit`, so that the null
stays a value and stops being a discriminant.

## 8. Invalidating derived content properly

`ProofreadPageMeta.default_body` is a cached fetch with no freshness tracking,
and `_apply_placeholder_enrichment` (`page_processors.py:515`) only fills it
when it is `None` — so it never refreshes. If an index's file is re-uploaded
with a better OCR layer, every derived body under it is silently stale
forever.

Do not put a TTL on it. Key it to what it is derived from: the index's
`FileBlob.file_sha1`, which already exists and which `_scan_check` already
trusts as the "same upload" oracle. Store the blob identity alongside the
derived body, and the fill condition becomes `derived_from != current_blob`
instead of `is None`. The same applies to `source_image_url`, `thumb_url` and
the raster paths — all derived from the same upload.

This is a proper invalidation key rather than a guess, and it is what makes
§3's "the proposed content is real content" safe to rely on.

## 9. Pre-flight before the migration

The backfill is "rows with `pageid` not null become `WikiPage` rows", which
assumes `pageid`, `revid` and `latest_revision_pk` agree today. Since
`sync.py:715` records that the head columns have more than one writer, they
may not. Run this against a real database first:

```sql
-- rows where the head denormalisation disagrees with the revision store
SELECT count(*) AS inconsistent
FROM page
WHERE (pageid IS NULL) <> (latest_revision_pk IS NULL);

-- and the finer split, if the above is non-zero
SELECT
  sum(pageid IS NULL AND latest_revision_pk IS NOT NULL) AS revision_without_pageid,
  sum(pageid IS NOT NULL AND latest_revision_pk IS NULL) AS pageid_without_revision,
  sum(revid IS NOT NULL AND latest_revision_pk IS NULL)  AS revid_without_revision
FROM page;
```

A non-zero result is not merely a migration problem — it is a live bug, and
which direction it skews says which writer is wrong.

## 10. What this note does *not* propose

The approval policy is a separate question with a separate justification, and
it should not ride along on this change.

- **Justified by provenance** (independent of SHA-1): creates never touch the
  matching path, per §6. This is the large one.
- **Justified by reliability** (depends on SHA-1 being trustworthy now): auto-
  confirming `title_match` pairings when `_scan_check` reports `ok`. The
  argument is that `compare_pages` only ever compares a pair already chosen by
  title — namespace role plus page number — so the hazard is two pages at the
  same number that are not the same leaf, and `FileBlob.file_sha1` already
  hard-blocks that case (`ScanStatus.mismatch`). The residual gap is
  `ScanStatus.unverifiable`, where one side has no `File:` blob and page-number
  correspondence rests on nothing. That is where a human still adds
  information.

Keeping these apart matters: presented together, a change that is mostly a
tightening reads as a loosening.

## 11. What the split introduces

Honest costs, none of them blocking:

1. **A join on the hot read paths.** `effective_state`, `stat_bulk` and the
   listings move from column reads to `LEFT JOIN wikipage`. These have already
   been tuned to one query per concern, so budget for re-tuning.
2. **A new consistency surface on write.** The fetch worker writes two rows.
   Mostly a win — PK-as-FK makes "revid without pageid" unrepresentable, which
   it is not today — but it admits one new bad state: a
   `WikiPage.latest_revision_pk` pointing at a `Revision` belonging to another
   page. Needs a guard in `record_head_revision` or a written invariant.
3. **Deletion semantics become a decision.** A page deleted upstream drops its
   `WikiPage` row and keeps its `Page`, journal, links and meta — expressible
   for the first time. Dropping looks safe because `Revision` keys to `Page`
   and so anchors still resolve, but it should be decided rather than fallen
   into.
4. **The null relocates; it does not vanish.** `wiki_page is None` is still a
   check. The entire payoff is the resolver discipline — sync takes a page with
   a revision, the VFS takes the name and never asks. Without that enforcement
   this buys a join and keeps the branching. This is a review habit, not a
   schema property, and it is what decides whether the change was worth making.
5. **Every API response composes two rows.** Broad rather than hard, and a good
   moment to stop serialising the raw ORM shape outward.

## 12. Tables dropped rather than moved

Two tables hung off `page` and were dropped in step 2 (`f8c0a6e2d493`) rather
than repointed, because each needs rethinking before it has a right key. Their
shapes are kept here so that rethinking starts from what existed.

### Transclusion

A mainspace page pulling in `Page:` content via
`<pages index="..." from="N" to="M" />`. Meant to support fetching "the Index
plus any work that transcludes it" (`FetchKind.transclusion`, still declared
and still unimplemented) and invalidating a composed work's rendered view when
one of its pages changes. **Nothing ever wrote a row.**

| Column | Type | Notes |
|---|---|---|
| `pk` | int, PK | |
| `site_pk` | int → `site.pk` | |
| `source_page_pk` | int → `page.pk` | the mainspace page doing the transcluding |
| `index_title` | str, indexed | target `Index:` title, as a string |
| `from_page` | int | |
| `to_page` | int | |

Open questions for a redesign: the target should be the Index's *title* (pk),
not a string; a `<pages>` tag can also use `fromsection`/`tosection` and
`include`/`exclude`, which a `from`/`to` range does not capture; and the source
is derived from fetched content, so it plausibly belongs to the wiki side of the
split rather than to the address.

### FileMeta

Provenance for `File:` pages. For images cropped out of a scan page it held
the crop geometry, in source-raster pixels -- which is also the input a
templated-region OCR run iterates over.

| Column | Type | Notes |
|---|---|---|
| `pk` | int, PK | |
| `page_pk` | int → `page.pk`, unique | the `File:` page described |
| `origin` | `remote` \| `paste` \| `ocr` | fetched; pasted as a screenshot; produced by region OCR |
| `source_page_pk` | int → `page.pk`, nullable | the scan page it was cropped from |
| `source_page_number` | int, nullable | |
| `crop_x`, `crop_y`, `crop_w`, `crop_h` | int, nullable | pixel geometry on the source raster |

It was exposed at `GET`/`PUT /pages/{pk}/file-meta`; no client used either.

Open questions for a redesign, driven by creating a work *from the client*
(an Index, its backing file and its pages, before any of them exists on a
wiki): the `File:` side is then only a title, so file attributes that exist
before an upload would key to `title`; crop geometry in raw pixels has the same
problem annotations had before they were normalised to fractions of the image
(`docs/design/scan-image-modeling.md`); and a *prospective* upload is not a
`FileBlob` -- a blob describes bytes the wiki holds, which is why `FileBlob`
stays on `page` for now.
