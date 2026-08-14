# Upstream sync — TODO

Only unfinished work. What is already built — the revision store, `RevisionLink`
/ `PageLink` / `IndexLink`, the content-model comparison, the sync report, the
proposal endpoint, `Promotion`/`PromotionBatch` and the incremental-fetch
planner — is recorded in `docs/done/upstream-sync-built.md`.

Reasoning, rejected approaches and policy live in
`docs/design/upstream-sync-discussion.md`; measured ProofreadPage hash behaviour
lives in `docs/reference/proofread-page-sha1-discordance.md`.

## Priority 1 — blocks mass promotion

- [ ] **Push-path safety** (discussion §8), worth doing independently of sync
      because the silent-overwrite-on-create gap exists today:
      `baserevid` + `createonly` on every create / `nocreate` on every update
      + API error-code mapping (`articleexists`, `missingtitle`,
      `editconflict`, `protectedpage`, `abusefilter-*`, `spamblacklist`) to
      distinct outcomes + post-push content verification (MediaWiki may
      auto-merge, which is a content change nobody reviewed).
- [ ] **The rest of the §7 transform chain.** Only the `pagequality user=`
      rewrite is implemented. Level capping, local-only templates/`File:`s and
      staging-host URLs are named checks that want their own `pass`/`warn`/
      `block` verdicts.

## Priority 2 — seeding a work that exists only upstream

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

2. **Downward promotion through `Promotion`/`PromotionBatch`** — the built
   promotion path with source and target swapped. Same preflight chain, same
   queue, same audit trail. This is what the data model has to support
   regardless: a set of changes derived from another site is the same object
   whichever way it points, and building it only for the outbound direction
   means building it twice.

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

## Priority 3 — incremental fetch, remaining gaps

The `list=recentchanges` planner is built (see done/). Deliberately not
half-covered, and still open:

- [ ] **Moves and deletions.** They are `log` entries needing
      `list=logevents`, and discussion §5 wants them *classified*
      (`redirect`/`deleted`/`moved`), not merely noticed. `rctype` stays
      `edit|new` so the gap is visible rather than apparently handled.
- [ ] `probe_pages(titles)` over `prop=revisions`, 50 titles per request, as
      the complement: bounded by the size of the work rather than by wiki
      activity, and with no retention horizon. Worth having for the "watermark
      is ancient" path, which currently refetches everything known.
- [ ] Note that this is for *planning*, not safety. The `baserevid` precondition
      covers the race between fetch and push; they are complementary.

## Priority 4 — model tidying, agreed but not scheduled

- [ ] Rename `Commit` → `PushLog` (discussion §12).
- [ ] Normalise the remaining `Page` head columns (`text`, `revid`,
      `remote_timestamp`, `contributor`, `comment`) behind
      `head_revision`/`head_content`, so the denormalisation has one writer.

## Outstanding test coverage

The two-wiki harness and the first two fixtures are in place (see done/). What
is still missing:

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
</content>
