# Upstream sync — considerations

Background reasoning for promoting locally proofread pages to a canonical wiki.
The immediate work list is `upstream-sync-TODO.md`; the measured facts about
ProofreadPage hashes are in `proofread-page-sha1-discordance.md`. This file is
the *why*: decisions taken, approaches rejected, and the things that will bite
whoever implements the next piece.

Motivating case, and the acceptance test for the whole feature:

| | |
|---|---|
| local | `…lan/wiki/Page:The_principles_of_mechanics…(Hertz,_1894).pdf/101` |
| upstream | `…en.wikisource.org/wiki/Page:The_principles_of_mechanics…(Hertz,_1894).pdf/101` |

The Hertz work is **already genuinely diverged** — others edited upstream,
equations were added locally — so it is a real fixture, not a synthetic one.

---

## 1. Why the push direction is riskier

Pull is private: worst case we clobber our own staging wiki. Push is public and
attributable. The edits themselves are presumably fine; the risks are **volume,
automation optics, and silent systematic error** — a normalisation bug
replicated across 400 pages is embarrassing in a way one bad edit is not, and it
draws attention to automation an observer cannot inspect.

It is all revertible, so the goal is not "never err" but **every mistake
bounded, visible, and undoable in one action**: explicit human approval per
batch, bounded batch size stated before approval, every edit traceable to a
batch, one-click rollback.

## 2. What MediaWiki will and will not let us do

**Remote history is append-only and immutable.** There is no rebase, no force
push, no history rewriting of any kind. Every push appends exactly one revision,
and its content must already incorporate whatever the target did in the
meantime. This single constraint shapes everything below.

Consequences:

- **1:1 revision replay is the happy path, not an invariant.** Replaying N local
  revisions as N remote revisions works only while the target has not moved. The
  moment someone edits upstream mid-sequence, the first replayed revision would
  clobber them, and the sequence degrades to one merged push.
- **Divergence cannot be resolved by finding the fork point.** Even knowing
  exactly where two histories separated, you cannot replay across the gap. So
  the remedy is *forward re-anchoring*: flag the divergence, have a human make
  the two sides content-identical in the UI, and record a new correspondence
  from that point. You create a base going forward rather than discovering one
  in the past.
- **Therefore no cross-wiki history walking is needed.** An earlier design had a
  four-rung "base ladder" whose second rung intersected both revision histories
  to discover a merge base. It is deleted: the anchor is recorded when a page is
  pulled, verified against the target head at push time, and re-established by
  hand when it breaks. `rvlimit=1` — the current revision — is all a push ever
  needs, because without knowing the current remote revision you cannot push on
  top of it at all, and we do not support force overwrite.

## 3. Why hashes do not identify pages across sites

`Content.content_sha1` is our own hash of the bytes the API served, and it is a
good identity token **within one site** — dedup, change detection, "did this
edit actually change anything". It is **not** a cross-site join, and the design
must not lean on it as one.

The reason is specific to ProofreadPage: a `Page:` body carries its own
metadata in the text.

```
<noinclude><pagequality level="3" user="Hesperian" /></noinclude>…
```

`user` is a username on *that* wiki, and `level` is that wiki's proofreading
state. Proofreading a page locally is precisely the act of changing both. So
two pages that are the same transcription will routinely hash differently, and
the divergence grows exactly as the work progresses. A hash match is strong
evidence of sameness; a mismatch is no evidence of difference at all.

This is why correspondence is **asserted and recorded** (`RevisionLink`) rather
than computed, and why comparison has to be **content-model aware** — comparing
body text while treating the pagequality header as metadata with its own
rules (level is significant and directional; user is required but not
comparable). See also `proofread-page-sha1-discordance.md` for the separate
problem of historical revisions whose stored hash predates a serialization
change.

### 3a. …but the comparison's verdict can be hashed

None of the above says hashing is useless here — it says hashing *the bytes* is.
The comparison already normalises before it decides: it blanks the site-local
field (`user`) and keeps the significant one (`level`). Hash the result of that
normalisation and you get a token whose equality means what the comparison
means, and `Content.comparable_sha1` is exactly that — precomputed once when the
content row is written.

The distinction matters because the anchor search is the hot path: it walks a
page's stored revisions newest-first, and it used to parse every one of them on
every walk. It now compares two strings per revision and parses only the one it
settles on, for the significance the digest deliberately does not carry
(`identical` and `metadata_only` hash alike — they differ only in the username,
which is the reviewer's business and not the matcher's).

Two properties keep this honest. Digests are compared only between rows of the
same content model, because a match across models would be an artefact of the
normalisation rather than a fact about the text. And a missing digest — a row
written before the column existed — falls back to the full comparison rather
than reading as a difference: not-computed is an unanswered question, not a
"no". The digest is a cache of a decision, not a second identity; rows are still
keyed and deduped by `content_sha1`.

## 4. A curated mirror is the goal, not a cost

Earlier drafts framed this as "probe, don't mirror", treating local copies of
remote state as overhead to minimise. That was the wrong emphasis and it pushed
the design away from what is actually wanted: **a curated subset mirror of the
works we care about**, held locally so comparison, diffing and review are
fast, offline, and inspectable.

What we do *not* want is an indiscriminate copy of a whole wiki. The subset is
chosen — a work, its Index, its Pages, its templates — and kept current. So:

- Fetch is incremental, not because storage is precious, but because refetching
  400 unchanged pages to find the two that moved is slow and rude to the wiki.
- The revision store keeps history sparsely: revisions we have actually seen.
  `Page.history_complete_from_revid` exists so a reader can tell "we hold these
  revisions" from "these are the revisions that exist".

## 5. Target page state — the cases that must fail, not merge

Pairing asks "is there a page there?". That is not enough: a title can be
occupied by something that is not a transcription.

- Classify the target before promotion: `normal`, `redirect`, `deleted`,
  `moved`, `protected`, `missing`. Anything but `normal` (or `missing` for a
  create) fails the item for manual handling. None of these are automatable.
- **`deleted` is not `missing`, and `prop=revisions` cannot tell them apart** —
  both come back missing. Separating them needs
  `list=logevents&letype=delete&letitle=…`. Creating a page that was
  *deliberately* deleted (copyright problem, out of scope, a community
  decision) is a far worse mistake than creating a new one.
- A `redirect` may be a legitimate target or a trap. Never pass `redirects=1`,
  which would silently retarget the push.

## 6. The scan-offset failure

If the two sides' backing scans are different uploads, local page 101 is not
target page 101 and every promotion in the work is silently off by an offset.

- Compare `FileBlob.file_sha1` of the `File:` on both sides. A mismatch is a
  hard block. Where files differ but page counts match, allow an explicit
  constant offset confirmed against a side-by-side scan spot-check.
- Where the target has no `File:` at all the check cannot run. That is *not* a
  reason to block — `Index:` and `Page:` can be created without one, and
  ProofreadPage permits it — but it means correspondence rests on title/offset
  assertion with nothing to validate it. Flag the pairing
  `correspondence_unverified`.

## 7. Body transformation

The local body cannot be pushed verbatim:

- **`<pagequality>` header** — rewrite `user=` to the account performing the
  push; the local username may not exist on the target.
- **Quality level** — cap promoted levels at 3 (Proofread). Wikisource requires
  validation be done by a *different* user than the proofreader, so asserting
  level 4 via automation from a staging wiki is the wrong look. Never downgrade
  an existing target level.
- **Local-only templates and modules** — `{{…}}` / `{{#invoke:…}}` that redlink
  on the target produce visible breakage across every promoted page. Block.
- **Local-only `File:` references** — `IndexMeta.short_name` generates names for
  extracted illustrations that exist only locally. These render as redlinks
  rather than failing the save; block by default with an override. Uploading
  inline illustrations is tractable (own work, clear licensing, small) and worth
  scoping in later; backing scans are a separate case-by-case decision.
- **Absolute links to the staging host** — any `wikisource-debian-13.lan` URL is
  a hard block; broken and mildly disclosive.

Implement as an ordered list of named check/transform classes each returning
`pass` / `warn` / `block` plus the rewritten body, so the UI can render the
chain and a new rule is a class rather than a pipeline change.

## 8. Conditional writes — measured, not assumed

Verified against a real wiki and MediaWiki REL1_43 source:

- **`baserevid`, not `basetimestamp`.** `basetimestamp` has one-second
  resolution (`EditPage` ~line 2310 compares timestamps), so two edits in the
  same second are indistinguishable and the push silently overwrites — exactly
  the workload a bot generates. It is *also* suppressed against your own
  account (`userWasLastToEdit`, ~line 2329, "Suppress edit conflict with
  self"), which matters because a previous batch runs as the same bot.
  `baserevid` compares revision ids exactly, and `ApiEditPage` only forwards
  `wpEdittime` when `baserevid` is unset, so the self-suppression branch never
  fires.
- **`createonly=1` on every create, `nocreate=1` on every update.** The current
  push path sends neither, so a page created on the target since our last look
  is silently overwritten.
- **Even with `baserevid`, MediaWiki may auto-merge** rather than conflict
  (`EditPage` ~line 2388 tries `mergeChangesIntoContent`). That is a content
  change nobody reviewed, so after each push, compare our hash of the newly
  served content against what we submitted; unequal means it merged, and the
  item goes back to review.
- Map API error codes (`articleexists`, `missingtitle`, `editconflict`,
  `protectedpage`, `abusefilter-*`, `spamblacklist`) to distinct outcomes.
  Everything non-conflict currently collapses into one stringified exception.
- `Commit.result_revid` stays authoritative regardless. The server guard
  narrows the race; it does not replace our own bookkeeping.

## 9. Summaries, attribution, rate

- Honest, configurable summary template. Transparency is the cheapest defence
  against the "opaque mass edit" objection.
- Set the bot flag only if the account actually has it. Using `bot` to hide
  edits from RecentChanges is precisely the optics failure to avoid.
- Respect `{{nobots}}` / `{{bots|deny=…}}`.
- Non-zero `put_throttle` and `maxlag` for the upstream site, **not** shared
  with the local site's settings.
- Consider requiring the pushing account to have some manual edit history; a
  brand-new account mass-editing is the fastest route to a block.

## 10. Batching, rollback, guardrails

- Hard cap per batch (~50), overridable with a typed confirmation.
- Server-side rate limit per target site, enforced in the worker.
- An abort that stops the worker between pages.
- `Site.is_public` marking, driving extra confirmation and loud UI treatment.
  The local wiki stays frictionless.
- Minimal-grant BotPassword for the target (edit; not delete, not protect).
- **Rollback per item** restores the revision preceding our push, via
  `undo`/`undoafter` rather than pushing a recorded body, so it registers as a
  proper revert in history. **Refuse to roll back blind:** if the target head is
  no longer our `result_revid`, someone edited on top; surface it. Batch
  rollback is itself a batch — same machinery, same audit trail — and reports
  partial results honestly.

**Do not ship mass promotion before rollback exists.** Mass commit without mass
revert is the exact shape of the risk this document is about.

## 11. Review UI

Review and approval belong in the viewer: iteration on the IntelliJ SDK is much
slower, and triaging dozens of diffs is a web-shaped task. Conflict
*resolution* is IDE-shaped — IntelliJ has a real three-way merge UI and
PSI-level wikitext support — so split by task, with a shared `body_override`
seam so both write to the same place.

The non-obvious parts of the review screen:

- **Target banner.** Full-width, unmissable when the target is public, naming
  the host. The single most valuable pixel in this feature is the one that stops
  someone approving against the wrong site.
- **Include-checkbox defaults carry the policy**: clean and promotable →
  checked; everything else → unchecked; blocked → disabled. The safe batch is
  the one you get by not thinking.
- **Approve states the consequence in words** and requires an echoed page count.
- Rollback stays available on the batch page permanently.
- `buildLineDiff` (`viewer/src/lib/diff.ts`) is line-based; word-level
  intra-line diff would help these bodies. Later.

## 12. Naming

`Commit` is misnamed. It reads like a canonical object — a git commit — when
the canonical representation is `page → revision → slot → content`. What the
table actually holds is *what we asked MediaWiki to do and what happened*:
append-only, one row per API call, failures included. It should be `PushLog`.

The corollary is that a push *queue* is a different thing with a different
lifetime — mutable, reviewable, cancellable — and belongs in its own table
(`Promotion`) rather than as a status column on an audit log. Overloading one
table with both is how this became confusing.

## 13. Open questions

1. **Per-page or per-work approval for routine work?** Per-work approval of
   clean pages is the ergonomic goal once trust is established. Start strict.
2. **Scan (PDF/DjVu) upload** — provenance and licensing differ per work and per
   target (Commons vs local). Deferred pending a real case.
3. **How is an anchor first established for a work already staged without one?**
   Probably: pull now, take the current target head as the anchor, and treat
   local changes as a patch relative to local history. Needs proving on Hertz.
