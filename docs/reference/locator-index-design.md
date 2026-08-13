# Back-of-book locator index — design

Status: **first cut implemented** (`src-py/wtbot/locator_index.py`,
`src-py/wtbot/api/locator_index.py`). This records the problem, the API
contract, and — importantly — which parts of it are solid readbacks of the
wikitext versus the one inferential rule worth double-checking against a real
book before trusting blindly.

## The problem

Transcribing a back-of-book index or a numbered-proposition list means
constantly answering "what does this reference point at?":

- Hertz's *Principles of Mechanics* back-of-book index says "ACCELERATION,
  273" — 273 is a **paragraph number** (Hertz numbers his definitions), and
  building the entry means finding which `Page:` carries
  `<section begin="p-273" />` for it, e.g.:

  ```wikitext
  <section begin="p-273" />{{anchor|p-273}}273. '''Definition'''. The
  instantaneous rate of change of the velocity of a system is called its
  acceleration. ...<section end="p-273" />
  ```

  so the transcriber can build the `{{double link|Page:...#p-273|...|273}}`
  the "Index to definitions" page needs.
- Other works' back-of-book indexes reference a **printed page number**
  instead of a paragraph, resolved not from section tags but from the Index's
  own `<pagelist>` tag, which maps *scan* page numbers to *printed* page
  labels:

  ```wikitext
  Book 1 Chapter 2: <pagelist from=82 to=94 82=48 />
  ```

  (scan page 82 is printed page "48"; 83 is "49"; …).

Two different locator schemes, same underlying need: given a locator typed
while transcribing, resolve it to the `Page:` that holds it.

## What this module does *not* try to do (yet)

Building the `{{double link}}`'s **second** argument — the mainspace
chapter/article that transcludes the resolved `Page:` — needs the
`Transclusion` table (`site_pk, source_page_pk, index_title, from_page,
to_page`), which already exists in the schema but is **not populated by
anything today**. Populating it means scanning mainspace pages for
`<pages index="..." from=".." to=".." />`, a new scan symmetrical to this
one. `PageNumberMatch`/`SectionMatch` therefore only ever resolve to the
`Page:` side, not the mainspace side — phase 2, not scoped here.

## Design choice: computed on read, not persisted

No new table, no build step, no staleness/invalidation problem. A work's
`Page:` set is at most a few hundred rows — a local SQLite read with no
network involved — cheap enough to recompute on every request rather than
maintain a cache. This also means a lookup sees **unsaved local edits**
immediately (via `PageStore.effective_body`, the same read that already
blends in uncommitted `EditJournal` rows) — exactly what you want while
you're the one typing the `<section begin=".."/>` tag you're about to look
up.

If this ever needs to change (a work large enough that per-request regex
scanning shows up in a profile), the natural next step is a persisted
`locator_index` table rebuilt from `PageStore` the same way `IndexMeta.
page_count` is today — not a different design, just adding a cache in front
of the same computation.

## `src-py/wtbot/locator_index.py` — pure, DB-free

Kept separate from the FastAPI router so the parsing/computation logic is
unit-testable without a database (mirrors the Kotlin side's habit of keeping
markup/text logic — `WtWrapRenderer`, `WtQuoteToggle` — free of IDE types).

### Section/paragraph anchors — `scan_section_occurrences`

A direct generalisation of the one-off script already used to build the
Tractatus section index (`re.compile(r'<section begin="([0-9.]+)"')` over
`pagegenerators.PrefixingPageGenerator`): scans one page's wikitext for
`<section begin=".."/>`, `<section end=".."/>`, and `{{anchor|..}}`, tagging
each occurrence with which of the three it is (`role`). `anchor_template` is
tracked separately from `begin`/`end` on purpose — Labeled Section
Transclusion itself creates no HTML anchor a browser can jump to, so
transcribers commonly add a companion `{{anchor|..}}` purely so a mainspace
`#p-273` fragment link resolves. A section with a `begin` but no
`anchor_template` is a real gap worth surfacing later (its `{{double link}}`
would point at a fragment that doesn't exist) — the data to detect that is
already here, even though nothing checks for it yet.

This half is a straight readback of the wikitext — no inference, no
uncertainty.

### `<pagelist>` parsing — `parse_pagelist_assignments` / `compute_labels`

Split into two functions on purpose:

- **`parse_pagelist_assignments`** extracts every explicit `N=value` /
  `NtoM=value` entry, across every `<pagelist>` tag on the Index (a work is
  routinely split into several — one per front-matter block/chapter, as in
  the Hertz example this was built against). Each key is clamped to its own
  tag's declared `[from, to]` — real Index pages reuse page numbers across
  tags in ways that would otherwise leak (see "Bugs found against a real
  Index" below).
- **`compute_labels`** resolves a label for a *specific* set of scan pages
  (the ones we actually hold a `Page:` row for — no attempt to enumerate an
  abstract 1..N range from the tag's own bounds). A page with its own entry
  uses it verbatim (`confidence: "explicit"`). Otherwise, the label is
  counted on linearly from the nearest earlier **numeral** entry
  (`confidence: "inferred"`) — arabic pages increment by one per scan page; a
  `roman`/`highroman` entry restarts the counter at i/I and continues in that
  numeral system until the next entry. A page with no preceding numeral
  anchor at all gets `confidence: "unknown"` and `label: null` — not a guess.

**The one inferential rule, flagged explicitly:** a `blank` (`-`) or `text`
(a literal label like `"half-title"`) entry does **not** shift the running
count for the pages after it — the formula counts straight through as if
that entry weren't there, so a title page or blank leaf sitting between two
numbered content pages doesn't throw off the numbering that follows. This
matches every example this was built against (every `-`/text run in the
Hertz Index is immediately followed by another explicit anchor before any
inferred page would need one), and matches the physical intuition that a
blank leaf still occupies a page slot. It is nonetheless an inference, not a
readback, and is the one part of this module worth checking against a real
rendered Index — ideally by comparing a handful of `compute_labels` outputs
against the printed numbers visible in the page images themselves — before
trusting it unreviewed on an unfamiliar work's front matter.

## Bugs found against a real Index, fixed

Testing against Hertz's actual `Index:` page (not the paraphrased snippet
this module was first built against) surfaced three real bugs, all in the
`<pagelist>` half:

1. **A key leaked outside its own tag.** The real Index has `Prefaces:
   <pagelist from=11 to=30 11=5 7to30=roman />` — note `7to30`, a range whose
   *start* is before that tag's own `from=11`. Without clamping, this range
   reached back into the *unrelated, earlier* "Front Matter" tag's `7=half-
   title`/`8=adv` and overwrote them. Fixed by clamping every key to its own
   tag's declared `[from, to]` (a missing `from` defaults to 1, matching
   ProofreadPage's own default; a missing `to` is left unbounded).
2. **A `roman`/`highroman` range didn't advance.** `7to30=roman` was being
   applied identically to *every* page 7–30 — each one independently "restart
   roman at i" — instead of anchoring only the first page of the range and
   letting the normal continuation rule carry ii, iii, … through the rest.
   Fixed: a style-switch keyword given as a range now anchors only its first
   page (after clamping, page 11 in this example); a bare number or literal
   roman numeral given as a range still applies per-page identically, since
   that really is the intent for e.g. `2to6=-`, a run of blank leaves.
3. **A fully bare `<pagelist />` (or no `<pagelist>` at all) resolved every
   page to `"unknown"`.** `Index:NeglectedArgument.pdf` has exactly this —
   `<pagelist />`, no attributes, no entries — and its real, documented
   ProofreadPage meaning is straight 1:1 arabic numbering across the whole
   work, not "we know nothing." This is a confident readback of
   ProofreadPage's own default, not a guess the "blank/text doesn't disturb
   the count" rule above is, so it's now seeded unconditionally as an
   implicit page-1 anchor — but only when `assignments` is empty outright; a
   work with some real pagelist data that merely doesn't cover an early page
   keeps the honest `"unknown"`.

## API — `GET /locator-index/{page-numbers,sections}`

```
GET /locator-index/page-numbers?path={vfs path}&query=273[&min_confidence=explicit|inferred][&limit=20]
GET /locator-index/sections?path={vfs path}&query=p-273[&roles=begin,anchor_template][&limit=20]
```

`path` is a *wikisource://* VFS path to either the `Index:` itself or any
`Page:` within it — same contract as `GET /pages/nav`, so a completion
feature running in the editor of one `Page:` (e.g. the "Index to
definitions" page itself) can ask about locators for the whole work without
resolving the Index title first.

`query` matches by exact-or-prefix (what a completion popup has after N
keystrokes), exact matches sorted first. Responses carry a ready-to-open VFS
`page` (`path`, `title`, `scan_page`) matching `page_nav.py`'s `PageNavEntry`
shape, plus the locator-specific fields (`label`/`confidence` for page
numbers; `section_id`/`role` for sections).

Both endpoints are pure GETs over the existing fetch cache — nothing here
fetches from the wiki, and nothing here writes.

## Tests

- `src-py/tests/test_locator_index.py` — the pure module: roman numeral
  round-tripping, `<pagelist>` parsing (single/range/quoted/multi-tag
  assignments, `from=`/`to=` never misread), the continuation algorithm
  (explicit vs. inferred vs. unknown, blank/text pages not disturbing the
  count, roman-style switching), and section/anchor scanning against the
  literal Hertz paragraph-273 snippet.
- `src-py/tests/test_locator_index_api.py` — the FastAPI layer: seeded via
  direct session inserts (same style as `test_page_nav.py`), covering both
  endpoints, the Index-vs-Page path equivalence, `min_confidence` filtering,
  prefix matching, `roles` filtering, and — the one that matters most for a
  live-typing completion feature — that an uncommitted `EditJournal` edit is
  visible to a lookup immediately.

## `GET /locator-index/dump` — everything, unfiltered

The two targeted endpoints answer one query each; `/dump` answers "what does
wtbot know about this work, altogether" in one call — every explicit
`<pagelist>` entry (`pagelist_assignments`), every `Page:` with its computed
label (`pages`, unfiltered — the same `compute_labels` pass the
`page-numbers` endpoint runs, just not narrowed to one query), and every
`<section>`/`{{anchor}}` occurrence, any role (`sections`). No new
computation — it is the existing pure functions run without a query filter,
composed into one response.

This is explicitly **not** the shape an interactive feature should reach
for. It exists for the viewer's inspection route, and — the more consequential
reason it's worth having — as the seed for IntelliJ SDK features that need a
work's whole relational shape rather than one query's answer: a
"documentation on hover" provider for a `{{double link|...|273}}` reference,
or "find usages" of a section id across the work, are naturally *symbol
search* problems, and `/dump` is close to what an IDE's index-building pass
would consume once. A live completion popup should still call `/sections` or
`/page-numbers` for the one locator being typed — dumping a whole work on
every keystroke is the wrong shape even though computing it is cheap.

## Exploring it: the viewer's Locator index route

`viewer/src/routes/locator-index/` — since all three endpoints are computed
live off the current cache, the debug viewer is where to poke at them: pick
a work, then either query section ids or page numbers, or switch to
"Everything" for the `/dump` view (three scrollable tables — pagelist
entries, pages, sections — with a shared substring filter, since a dump can
run to hundreds of rows). Query modes update live (debounced ~250ms, not a
submit button); each result row has a "copy path" action. `IndexPageSummary`
(`GET /viewer/indexes`, already backing `/indexes`) now carries `family`/
`code` so a VFS path can be built without a second round trip.

**Work selection**: a collapsible card tray (`WorkPicker.svelte`) rather
than a permanent sidebar list — expanded it's a full-width grid of cards;
clicking one selects it and collapses the tray to a one-line summary bar
(click it to reopen), so the results underneath get the full content width
instead of losing half of it to a list that is only useful during selection
itself.

## Future: consuming this from the plugin

Not built yet; the seam to build it against:

- `VfsBackend.lookupPageNumbers(path, query, minConfidence)` /
  `.lookupSections(path, query, roles)` — thin HTTP calls mirroring the
  endpoints above, plus a `FakeVfsBackend` implementation so a completion
  contributor is testable offline (same pattern as every other `VfsBackend`
  method).
- A completion contributor (or a live-template-driven insertion, matching how
  the Surround With work already prefers a live template over a modal
  dialog) offered inside `{{double link|...}}`'s third argument and — once
  phase 2's `Transclusion` resolution exists — able to fill the second
  argument too.
- Should sit behind a registry-key prototype switch, same as the rest of the
  text-editing features (`wikitext.editing.*`) — this is exactly the kind of
  feature worth trying two or three insertion styles for before committing to
  one.
