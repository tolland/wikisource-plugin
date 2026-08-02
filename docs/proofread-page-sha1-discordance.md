# ProofreadPage SHA-1 discordance

## Summary

For some historical `proofread-page` revisions on English Wikisource, the
SHA-1 reported by MediaWiki is not the SHA-1 of the main-slot text returned by
the API or XML export.

This is not an encoding difference. The reported value describes MediaWiki's
stored content representation; ProofreadPage can deserialize that content and
serve a different `text/x-wiki` representation. Public read APIs expose the
latter, not necessarily the exact bytes over which the stored hash was
calculated.

Consequently:

- `Revision.sha1` is storage metadata, not always a portable content identity;
- XML-export SHA-1 values use the same stored hash and can disagree with the
  exported `<text>`;
- cross-wiki comparisons must use a SHA-1 computed from the content actually
  returned, unless the reported hash has first been verified against that
  content; and
- normal synchronization should record the upstream revision ID and a computed
  content hash when a page is pulled, avoiding later history discovery.

The problem observed here is specific to `proofread-page`. The sampled
`proofread-index` and ordinary `wikitext` revisions were self-consistent.

## The motivating example

The test page is:

```text
Page:Canadian patent 29537.djvu/2
```

Its first English Wikisource revision is `900114`. MediaWiki reports:

```text
SHA-1 hex:    425897494d2dce61e94808a0458462461a9d41c1
SHA-1 base36: 7qzy4bystlkoytnzaivpq46nv4bbd1d
```

Hashing the UTF-8 main-slot text returned for that revision instead produces:

```text
SHA-1 hex:    2eafc1d15c66328e1072a5117d853bbc66ca5d75
SHA-1 base36: 5gbqyl7yvj3b596oe01pgm83dxvpilx
```

The discrepancy is visible through both pywikibot and `Special:Export`.
Importing the export into a fresh wiki stores the exported text and recalculates
its hash, so the imported revision reports `5gbqyl7…`, not the source
revision's `7qzy4b…`.

The four upstream revisions are:

| Revision | Timestamp | Comment | Stored hash | Hash of served text | Equal |
|---:|---|---|---|---|---|
| 900114 | 2008-11-30 | `/* Proofread */` | `7qzy4b…` | `5gbqyl…` | no |
| 1193309 | 2009-08-14 | — | `ti1n0s…` | `ber7ri…` | no |
| 2650547 | 2011-04-02 | — | `d8royu…` | `ber7ri…` | no |
| 7673287 | 2018-07-22 | `Pywikibot touch edit` | `ber7ri…` | `ber7ri…` | yes |

Revisions `1193309`, `2650547`, and `7673287` return byte-identical text even
though their three stored hashes differ. MediaWiki's own diff API reports an
empty diff between the latter revisions.

## Hash encodings

The action API and pywikibot return a 40-character hexadecimal SHA-1:

```text
61ad96427deee611bb5bac3b8fa3318ceb46e06f
```

XML exports and MediaWiki database columns use a zero-padded, 31-character
base-36 representation of the same integer:

```text
ber7rim00nw9gknuje381xd89o14ne7
```

Conversion between these encodings is necessary, but it does not resolve the
content discordance:

```python
def mediawiki_sha1_base36(hex_digest: str) -> str:
    return base36(int(hex_digest, 16)).rjust(31, "0")
```

The project implementation is in `wtbot/wiki/sha1.py`.

## Read surfaces tested

For revision `1193309`, all tested public surfaces returned the same 1,608
bytes, whose hash is `ber7rim…`, while the stored hash is `ti1n0s…`:

| Surface | Recovers stored bytes |
|---|---|
| `action=query&prop=revisions&rvslots=main` | no |
| Legacy revision API without `rvslots` | no |
| `index.php?action=raw&oldid=…` | no |
| REST v1 revision endpoint | no |
| `action=parse&prop=wikitext` | no |
| `Special:Export` | no |

Changing the read API therefore does not recover the original stored
serialization.

## Transformation experiments

The diagnostic script tried the following representations of the served text:

- UTF-8, with and without a BOM;
- Windows-1252;
- UTF-16 and UTF-32, in both byte orders;
- LF, CRLF, and CR line endings;
- NFC, NFD, NFKC, and NFKD Unicode normalization;
- XML entity escaping, with and without quote escaping;
- an added trailing newline;
- trailing whitespace removal;
- removal of only the leading `<pagequality … />` element;
- removal of the complete leading
  `<noinclude><pagequality … /></noinclude>` block; and
- removal of the ProofreadPage header and footer wrappers.

None reproduced `7qzy4bystlkoytnzaivpq46nv4bbd1d`.

Run the experiment with:

```bash
.venv/bin/python src-py/scripts/compare_revision_sha1.py \
  --try-transformations
```

## What MediaWiki hashes

At the database level, `revision.rev_sha1` agrees with the main slot's
`content.content_sha1`. Both describe the bytes MediaWiki stored. They are not
independent values.

### `content_size` is not a byte length

`rev_len`/`content_size` disagrees with the served text even on revisions whose
hash agrees, and this is by construction rather than staleness. ProofreadPage
does **not** override `getSha1()`, so it falls through to core and hashes the
*serialized* form — the bytes the API serves. It **does** override `getSize()`
in both content classes, to sum the component parts:

```php
// includes/Page/PageContent.php
public function getSize() {
    return $this->header->getSize() + $this->body->getSize() + $this->footer->getSize();
}

// includes/Index/IndexContent.php
foreach ( $this->fields as $value ) { $size += $value->getSize(); }
```

Neither includes the `<noinclude>`/`<pagequality>` wrappers, nor — for an index
— the `{{:MediaWiki:Proofreadpage_index_template …}}` call and its field names.

Observed on a freshly synced local wiki, where the hashes agree in both cases:

| Page | Served bytes | `content_size` | Hash agrees |
|---|---:|---:|---|
| An empty `Page:` (`level="0"`, no text) | 86 | 0 | yes |
| An `Index:` | 1,918 | 1,582 | yes |

The empty `Page:` is the clearest case: its 86 served bytes are entirely
`<noinclude>` wrapper, and the header, body and footer are each empty, so the
sum is 0.

So the hash and the size measure different things. A hash may be compared once
normalized; a size may not be compared to a length at all.

### The stored blob is not wrapper-free

An earlier hypothesis here was that ProofreadPage stores a structured or
wrapper-free form and reconstructs the `<noinclude>` wrappers on the way out.
Reading the storage layer directly disproves it. For an empty local `Page:`,
joining `text` through `content_address`:

```text
old_text     : <noinclude><pagequality level="0" user="Tolland" /></noinclude><noinclude></noinclude>
content_size : 0
content_sha1 : olrw2f2f01ajvxtb4aj1bdt0j54pp6r
rev_len      : 0
page_len     : 0
```

The stored blob carries the wrappers in full and is byte-identical to what the
API serves; its SHA-1 is the SHA-1 of those 86 bytes. Only the *size* columns
diverge.

So the correct model is:

- `text.old_text` holds the serialization **as written at save time**;
- `content_sha1` is the SHA-1 of that same blob, so served and stored agree
  whenever the serialization format has not changed since the save — which is
  why current revisions are self-consistent, and why the pre-2018 English
  Wikisource revisions are not;
- `content_size`, `rev_len` and `page_len` all come from `getSize()`, which
  ProofreadPage overrides to a **semantic** size — transcribed content only,
  excluding the wrappers and, for an index, the template call and field names.

The size override is arguably deliberate rather than a defect: it makes a
`Page:`'s recorded length measure transcribed text, so an untranscribed page
reads as 0 bytes in history and page lists rather than as its markup overhead.

The exact historical serialization that produced the three old English
Wikisource hashes was not recovered. It is not available through the public
read surfaces tested above.

Import and normal API-save paths can also behave differently. `importDump`
can store the exported wikitext verbatim, while a normal ProofreadPage edit
passes through its content handler. The database-backed tests cover this
distinction.

## The 2018 touch-edit evidence

The `Wikisource-bot` revisions with the exact comment
`Pywikibot touch edit` appear to reserialize old ProofreadPage content. In the
Canadian patent fixture:

| Position relative to first touch | Revisions | Matches | Mismatches |
|---|---:|---:|---:|
| Before | 80 | 0 | 80 |
| Touch revision | 24 | 24 | 0 |
| After | 1 | 1 | 0 |

Additional dumps in `tests/fixtures/sha_checks` produced the following unique
`proofread-page` results:

| Category | Revisions | Matches | Mismatches |
|---|---:|---:|---:|
| Before a touch revision | 3 | 0 | 3 |
| Touch revision | 3 | 3 | 0 |
| Created after the provisional cutoff, without a touch | 1,095 | 1,095 | 0 |

These dumps contain 517 distinct pages and 1,101 distinct revisions from four
works, with no counterexample. Several dumps overlap, so revision IDs were
deduplicated before counting.

The three additional touch revisions occurred on 29 August 2018. Therefore
`2018-07-22T17:16:37Z` is not a global cutoff; it is only the timestamp of one
page's touch. The campaign covered at least July and August 2018.

The evidence supports this English Wikisource working hypothesis:

> A successful `Pywikibot touch edit` produced a self-consistent revision, and
> revisions written using the later serialization are expected to be
> self-consistent.

It does not establish that every old page was touched. A touch comment is
sufficient evidence for that revision, but it is not necessary: a later normal
edit may also have reserialized the page. Nor does a touch revision repair the
stored hashes of its ancestors.

## Synchronization consequences

### History discovery

Intersecting two complete histories using server-reported SHA-1 metadata is
unsafe for `proofread-page`. If history discovery is unavoidable, compare
hashes computed from the returned main-slot content:

```python
hashlib.sha1(revision.slots["main"]["*"].encode("utf-8")).hexdigest()
```

This requires fetching revision content rather than metadata alone.

### Preferred synchronization anchor

Normal plugin operation should not need to rediscover history. When pulling a
page, record:

```text
upstream revision ID
upstream timestamp
SHA-1 computed from the served main-slot UTF-8 text
```

The revision ID is the ancestry token. The computed hash detects
content-equivalent null or touch edits.

When pushing local edits:

1. Read the current upstream latest revision metadata.
2. If its revision ID equals the stored anchor, replay the local edits.
3. If the ID differs, fetch and hash only the current latest content.
4. If that content hash equals the anchor hash, advance the anchor and replay.
5. Otherwise, report an upstream conflict and require rebase or merge.

This makes the common operation require at most the latest revision's content,
not every historical revision.

The server-reported hash may still be used as a shortcut after it has been
verified against the served content, but correctness should not depend on the
2018-date or touch-comment heuristic.

## Reproducible evidence

- `src-py/scripts/compare_revision_sha1.py` compares live source and staging
  histories and runs transformation experiments.
- `src-py/tests/test_proofread_serialization.py` pins the historical
  English Wikisource discrepancy.
- `src-py/tests/test_content_sha1.py` verifies `rev_sha1`,
  `content_sha1`, import, and API-save behavior against the harness database.
- `src-py/tests/wiki_harness/dumps.py` parses declared and computed hashes from
  XML fixtures.
- `src-py/tests/fixtures/sha_checks/` contains the additional sampled exports.

## Current conclusion

For portable comparison, the authoritative token is the SHA-1 computed from
the served content. The stored SHA-1 is useful storage metadata and is commonly
self-consistent on later English Wikisource revisions, but it is not a
universal content hash for historical ProofreadPage revisions.
