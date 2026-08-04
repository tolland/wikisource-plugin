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

  Enforced in `wtbot.remote_link_store`, the only writer: append-only (no
  update, no retract), cross-site only (within one wiki, revision ancestry
  already says everything a link would), and idempotent on the pair with the
  first `origin` winning. Page-level correspondence is *derived* by
  `corresponding_page` walking `link → revision → page`, in either direction;
  a target redlink has no link, which is correct — there is nothing to compare,
  and "local present, target absent" is a pairing question, not a linking one.
  `origin=reconciled` records the forward re-anchoring of discussion §2.

## Now

Numbered as originally listed; items 1 (`RemoteLink`) and 3
(content-model-aware comparison) are done and moved to *Built* above.

### 2. Incremental fetch

Refresh a curated subset without refetching everything.

- [ ] `WikiClient.probe_pages(titles) -> dict[str, PageProbe]` over
      `prop=revisions&rvprop=ids|timestamp|user`, 50 titles per request; missing
      titles come back in `query.missing`.
- [ ] Fetch only pages whose revid differs from the one behind
      `Page.latest_revision_pk`. A 400-page work becomes ~8 calls plus the pages
      that actually moved.
- [ ] **A changed revid is not a changed page.** Null and touch edits bump the
      revid with identical content (four such in the Canadian patent fixture).
      Decide "diverged" from the content comparison after fetching, or every
      upstream maintenance run shows up as a false conflict.
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

- [ ] `POST /links/propose { index_page_pk, remote_site_pk }` → proposed
      revision pairs with confidence, plus the ones that could not be matched
      and the reason (no counterpart, ambiguous, target not `normal`).
      Confidence lives on the **proposal response only** — it is a property of
      a guess, and `RemoteLink` stores no guesses.
- [ ] `POST /links` to confirm one or many; `DELETE` to retract.
- [ ] Title normalisation compares namespace *roles* resolved per site, never
      numeric ids — `Page`/`Index` ids differ between installs.
- [ ] Never auto-confirm. Proposals are proposals.

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

- [ ] Build the diverged fixture on the two-wiki harness: copy a work across,
      edit both sides, assert the pairing reports divergence rather than
      silently promoting.
- [ ] Two sites with differing `File:` sha1s must refuse to link children.
- [ ] A batch targeting an `is_public` site must not run without an approval
      record.
- [ ] Use the harness as the dry-run sink for the whole batch path before
      anything points at en.wikisource.
