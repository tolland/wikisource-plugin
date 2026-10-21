# Generate transclusion pages from a PDF outline

The CLI supports an editable proposal followed by local page generation.
It generates Book subpages, leaves the root untouched, and saves through
EditJournal. It also renders Index pagelist wikitext from the edited YAML.
It does not publish to the wiki. Updating the Index template automatically
and structured plugin navigation are follow-on work described
in [the work outline design](../design/work-outlines.md).

## Generate a proposal

```bash
uv run wtbot dev propose-transclusion \
  --pdf-filepath /path/to/book.pdf \
  --title "Work" \
  --author "Author" \
  --level-type 1=Part \
  --level-type 2=Chapter \
  --level-type 3=Section \
  --output structure.yaml
```

The default level types are Part, Chapter, and Section; deeper levels
use Section unless mapped explicitly. Source numbers, including Roman
numerals, supply the number in generated paths. Configured level types
supply the type, so `--level-type 1=Book` turns a numbered part into `Book_1`.
Recognised front/back matter uses named paths. Other unnumbered divisions
are numbered amongst their siblings. Inspect the proposal to correct
ambiguous naming, numbering, and classifications.

`--depth` defaults to 99. Use a lower value for overly granular outlines.
Omitted descendants' scans are assigned to the retained ancestor. The full
source outline and PDF labels remain in `source` for future reuse. Missing
bookmarks produce a single Text page covering the PDF.

The proposal contains no root or Index destination. Those are supplied at
apply time, so the same proposal can be used for different destinations.
`source.file` contains only the PDF filename, with no local directory path;
the fingerprint identifies the source independently of where it is stored.
Loading an older proposal also strips any directory path from this field.
The work title can be set during extraction; if omitted, rendering uses the
apply-time root title without its namespace. `--translator` adds header
metadata. Categories can be added in YAML under `metadata.categories`.
`--force` on this command replaces an existing proposal file.

## Edit and preview

Edit nested `pages` entries in YAML. Each `path` is relative to its parent;
renaming `Part_1` to `Book_1` updates resolved descendant names automatically.
`title` supplies the descriptive heading in headers and links.

`scans: {from: 24, to: 31}` means inclusive, one-based physical scan numbers,
not printed page labels. A container sharing its first child's starting scan
can have `scans: null`. Parents transclude only their own opening material
and link to their children; the renderer does not duplicate the children's
content on the parent.

Each generated scan range also has editable printed-page numbering:

```yaml
scans:
  from: 8
  to: 11
  numbering: roman
  start: 7
```

This maps scan 8 to printed page vii and renders
`<pagelist from="8" to="11" 8="7" 8to11="roman" />`.
Extraction seeds `numbering` and `start` from the range's first PDF page
label, both with and without bookmarks. Styles are `normal`, `roman`, and
`highroman`. Missing or nonnumeric starting labels produce editable
`numbering: unknown` and `start: null` placeholders.

Set the starting value and style to correct an inferred mapping. Each range
is independent, so a later volume can restart at 1. Supplying `start` while
omitting `numbering` uses normal Arabic numbering. Range numbering overrides
`source.labels` for that range; if `start` remains null, stored labels and
the existing scan-number fallback remain in use. Older proposals without
these fields continue to work.

One range describes one continuous numbering run. There is no internal
override format: rare transitions inside a range can be corrected manually
in the generated wikitext, or represented by separate page entries.

```bash
uv run wtbot dev apply-transclusion \
  --structure structure.yaml --root-page "Book:Work" --dry-run
```

This is an offline preview: it validates selections and prints every
resolved title and generated wikitext, without contacting the API. Application
does not need the original PDF and does not re-extract it.

`--root-page` is required when applying, including for a dry run.
`--index-page` defaults to `Index:<source PDF filename>` and can be overridden
when the uploaded file has another name. Generated relative paths, full page
paths, and link targets use underscores, for example
`Book:My_Work/Part_1/Chapter_1`. Descriptive headings retain their spaces.
Spaces and underscores are equivalent when checking existing destinations.

Every scan must be covered by page selections or explicit exclusions, such as:

```yaml
exclusions:
  - scans: {from: 1, to: 2}
    reason: "Covers omitted from transclusion"
```

When removing pages manually, reassign their scans or add exclusions.
Duplicate paths, invalid paths, missing coverage, general overlaps, and
empty leaves prevent application. Exclusions must not overlap content.

Successive headings starting on the same scan are an allowed overlap:

```yaml
- path: Chapter_4
  title: "4. Bentham’s Method in Political Science"
  scans: {from: 222, to: 222}
- path: Chapter_5
  title: "5. Abstractive Fictional Methods in Physics and Psychology"
  scans: {from: 222, to: 223}
```

The earlier heading is assumed to occupy part of the shared first scan.
These ranges can be generated and applied before transcription exists,
without a blocking unresolved diagnostic. Initially both Book pages
transclude the whole shared scan. Later, add section markers to the Page
content and edit the Book pages' `<pages>` tags to use `fromsection`,
`tosection`, or `onlysection` as appropriate. The generator does not invent
markers; partial-page selectors in YAML are not yet supported.

## Generate Index pagelists from the structure

Use the edited page ranges and stored labels, without the original PDF or
any API access:

```bash
uv run wtbot dev extract-outline \
  --structure local/outlines/Foot-Virtues_and_vices-1978.pdf.yml
```

The output has the same headings and `<pagelist>` format as extraction from
a PDF, suitable for the Index template's `Page` attribute. Redirect stdout
to a file to save it. `--structure` and `--pdf-filepath` are mutually exclusive.

Structure input defaults to depth 99; `--depth 1` groups descendants beneath
their top-level heading. PDF input retains its default depth of 1.
The edited `pages` tree supplies section boundaries, even when `source.pages`
is empty. Explicit range numbering takes precedence over `source.labels`.
Stored labels supply numbering and literal labels where no range start has
been set. Missing or null labels fall back to physical scan numbers; they
are not inferred from chapter titles or OCR.

Unlike Book transclusions, an Index pagelist lists each scan only once.
Shared-start sections are combined under a joined heading. Containers without
their own scans have no separate pagelist unless collapsed with `--depth`.
Excluded transclusion scans remain in the Index output under an exclusion
heading. This command only prints wikitext; it does not edit the Index.

## Save locally

Start the updated wtbot API and use a registered site with namespace metadata:

```bash
uv run wtbot dev apply-transclusion \
  --structure structure.yaml \
  --root-page "Book:Work" \
  --index-page "Index:book.pdf" \
  --label local
```

Use the root `--base-url` option if the API is on another address (see
`wtbot --help`). `WTBOT_SITE_LABEL` can supply the site label.

The backend checks all destinations against its local title cache before
writing. If an address is already known locally, generation stops without
saving any pages. Use `--force` to replace its local content explicitly;
previous journal entries are retained. This does not check uncached remote
pages or change the normal commit workflow's concurrency checks.

The batch saves atomically and appears in `GET /commits/pending`, ready for
the existing review/commit workflow. No remote pages are created by either
command. The current synthetic VFS tree does not yet provide a general Book
namespace browser; saving these journal entries does not add that UI.
