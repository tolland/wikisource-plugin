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
  the Hertz example this was built against). No `from=`/`to=` parsing is
  needed to do this correctly: the digit-run key requirement means `from=`
  and `to=` never look like page assignments in the first place, so there's
  no exclusion list to maintain.
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

## Exploring it: the viewer's Locator index route

`viewer/src/routes/locator-index/` — since this is computed live off the
current cache, the debug viewer is where to poke at it: pick a work (reused
from the same `GET /viewer/indexes` list `/indexes` already shows, now
carrying `family`/`code` so a VFS path can be built without a second round
trip), pick section-id or page-number mode, type a locator, get results
live (debounced ~250ms, not a submit button) with a "copy path" action per
match. No new backend beyond `family`/`code` on `IndexPageSummary` — it's
a client over the same two endpoints described above.

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
