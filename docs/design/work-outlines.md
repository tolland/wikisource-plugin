# Work outlines, transclusion proposals, and page navigation

Status: PDF extraction, nested YAML proposals, validation, rendering, and local
journal application and pagelist rendering from edited YAML are implemented. See
[the CLI guide](../reference/transclusion-generation.md) for current behaviour.
Automatic Index attribute updates, persistent navigation APIs, plugin presentation,
and EPUB support below remain proposed.

## Purpose

Represent a work's structure once and use it to generate transclusion pages
and improve navigation in the IntelliJ plugin. A work with 843 scans should
be navigable by part, chapter, section, and printed page label when those
are known, while retaining access to every scan by its existing address.

Structure may come from PDF bookmarks, EPUB navigation and reading order,
or manually authored YAML. Printed page labels are a separate layer: a
ProofreadPage Index's pagelist can supply useful labels even when there is
no outline. Missing structure must not prevent transcription or navigation.

The longer-term goal is to drive both the `Page` attribute of the
`:MediaWiki:Proofreadpage_index_template` template (the structured pagelist
content on the Index) and the Book page transclusion structure from this
representation. Maintaining both manually becomes burdensome across many
books. The initial CLI scope is generating new structure, not maintaining
or reconciling previously generated pages.

## Existing building blocks

- `src-py/wtbot/cli/commands/pdf_outline_utils.py` reads PDF bookmarks and
  labels. `PdfOutline` filters by depth, merges bookmarks sharing a scan,
  and produces disjoint ranges for pagelists. That merged representation
  cannot preserve all structural relationships.
- `wtbot dev extract-outline` renders those ranges as pagelists.
- `src-py/wtbot/api/locator_index/` already exposes pagelist assignments,
  computed labels, confidence, and canonical Page references. Its section
  matches describe wikitext section markers, a different concept from book
  outline nodes.
- `src-py/wtbot/api/vfs.py` exposes the canonical wiki file tree. The new
  presentation must preserve its page identities and read/write behaviour.

Keep existing pagelist generation behaviour available. Introduce a shared
structural extraction layer before flattening or combining bookmarks, rather
than making the existing flattened entries the structural source of truth.

## Three related representations

1. **Source outline:** the author's available hierarchy and reading order,
   preserving source destinations and provenance.
2. **Editable transclusion proposal:** nested pages, relative paths, metadata,
   and explicit content selections to apply after review.
3. **Navigation view:** structure plus scan references and effective labels,
   served by the backend for optional plugin presentation.

These share typed domain objects and source anchors, but are not identical.
A generation depth limit changes the proposal, not the preserved source outline.
Wiki subpage names are editorial choices, not identities for source nodes.

## Nested proposal format

Use versioned YAML with children under `pages`. Every `path` is relative to
its immediate parent. Nesting expresses parentage; no redundant `parent`
field or repeated full path is required. Generated path segments and resolved
page paths use underscores; descriptive titles keep their spaces. The proposal
contains no destination root or Index title: `--root-page` is required at apply
time and `--index-page` defaults there to `Index:<source PDF filename>`.

```yaml
schema_version: 1
source:
  kind: pdf
  file: book.pdf
  fingerprint: "sha256:..."
  scan_count: 650
generation:
  depth: 99
  level_types:
    1: Part
    2: Chapter
    3: Section
metadata:
  title: "Work"
  author: "Author"
pages:
  - path: "Contents"
    title: "Contents"
    scans: {from: 8, to: 9}
  - path: "Part_1"
    title: "Introduction to Part I: Rationale and Foundations"
    scans: {from: 20, to: 23}
    pages:
      - path: "Chapter_1"
        title: "Goal-Directed Systems: An Evolutionary Approach to Life and Consciousness"
        scans: {from: 24, to: 31}
        pages:
          - path: "Section_1"
            title: "The Leibowitz Challenge: The Kantian Epistemological Gap"
            scans: {from: 32, to: 35}
```

This is an excerpt, not a complete coverage manifest. `source.file`
stores only the filename, never the local directory path; the fingerprint
provides source identity across machines. All scan numbers are
one-based physical scan positions, inclusive at both ends. They are never
printed page labels. `scans` describes a node's own transcluded content;
it does not include its descendants' content. A structural container can
have `scans: null` and children. Its navigation extent is derived separately
from its own selection and descendants.

Scan selections also carry editable `numbering` (`normal`, `roman`,
`highroman`, or `unknown`) and `start` fields. Proposal generation infers them
from the first scan's PDF label, independently of bookmark availability;
unknown numbering uses `start: null`. An explicit start overrides imported
labels across the range, using normal numbering if its style is omitted.
Ranges may independently restart at 1. Missing fields in older proposals
retain imported-label fallback. Do not model internal numbering transitions:
edit the output manually or split into separate page entries for those cases.

Changing `Part_1` to `Book_1` changes all resolved descendant wiki titles.
The actual heading remains in `title`, for headers and navigation labels.
Optional source-node references can connect proposal entries to the source
outline; these references must survive path edits. Handwritten proposals
need not invent IDs merely to express their tree.

## Naming and numbering

Accept repeatable mappings such as `--level-type 1=Part`,
`--level-type 2=Chapter`, and `--level-type 3=Section`. Numbered structural
paths contain the type and index, not the descriptive heading.

Mappings are defaults, not a claim that every bookmark at a depth has the
same role. Contents, Preface, Acknowledgments, Notes, References, and Index
need named paths. Notes may have chapter children without being another
part. Preserve these exceptions in the proposal for editing and flag
ambiguous classifications rather than silently numbering everything as Part.

Prefer explicit source numbering where it can be recognised reliably. In
the motivating example, Part 2 begins with Chapter 6, not Chapter 1.
For unnumbered headings, default to sibling numbering; allow configurable
continuous numbering by type where required. Record generated choices in
the proposal so apply never needs to infer them again.

Normalise NUL padding and incidental whitespace in imported headings.
Preserve meaningful punctuation. Validate relative path segments, including
slashes and wiki-invalid characters, and detect duplicate resolved titles
after MediaWiki title normalisation. Do not derive namespace IDs from fixed
upstream constants; use the site's namespace information.

## Depth and coverage

Default generation depth to 99: ordinarily preserve the author's divisions.
Depth means source outline level, not a level guessed from heading text.
Reject values below 1. A lower limit is useful for unusually granular books.

Apply the limit before calculating proposal ranges. At depth 2, Chapter 1
in the example owns scans 24–59, absorbing all its sections. At depth 3,
its own opening is 24–31 and its sections own subsequent ranges. Do not
delete descendant nodes from an already ranged tree and lose their scans.

Keep the full source hierarchy for navigation even when transclusion
generation is shallower. A later editor collapse operation must explicitly
transfer the removed descendants' content selections to the ancestor;
manually deleting YAML entries alone does not imply that transfer.

For ordinary ordered bookmarks, a node's subtree ends immediately before
the next bookmark at the same or a shallower level. Its own introductory
content ends before its first retained child. Leaves run to the next
retained boundary, or the end of the document. Validate source order and
destinations rather than silently sorting malformed hierarchy into a
different meaning.

Account for scans before the first bookmark and after the last. Default
proposals cover every scan; explicit exclusions may omit covers, blanks,
or other unwanted material and must carry a reason. Validation rejects gaps
and general overlaps, allowing the shared-start case below between successive
content selections. Exclusions must not overlap content.

Preserve bookmarks sharing a scan rather than merging their titles. When
successive content headings start on scan N, generate the earlier heading
with `scans: {from: N, to: N}`. The following heading starts at N and runs
to its normal end. Multiple successive headings may each occupy part of N.
This common case does not create a blocking `unresolved` diagnostic.
A parent starting with its first child can still be a container with no
own transclusion; it does not need to duplicate the child's first scan.

This deliberately generates useful scaffolding before transcription exists.
The editor later adds section markers to the Page content and adjusts the
Book pages' `<pages>` selections with `fromsection`, `tosection`, or
`onlysection` as appropriate. Until then, both transclusions include the
shared whole scan. Do not invent section markers automatically. Typed
partial-page selections in YAML remain a future enhancement.

## Two-stage workflow

Proposed command names:

```bash
wtbot dev propose-transclusion \
  --pdf-filepath book.pdf \
  --level-type 1=Part \
  --level-type 2=Chapter \
  --level-type 3=Section \
  --depth 99 \
  --output structure.yaml

wtbot dev apply-transclusion --structure structure.yaml --root-page "Book:Work" --dry-run
wtbot dev apply-transclusion --structure structure.yaml --root-page "Book:Work"
# Explicitly replace existing generated destinations when needed:
wtbot dev apply-transclusion --structure structure.yaml --root-page "Book:Work" --force
```

Proposal generation makes no wiki edits. The editor can rename or move
nodes, correct classifications, adjust selections, and inspect warnings.
Apply validates the edited document and uses its explicit paths and ranges;
it does not re-extract the PDF or recalculate editorial decisions.

Render a complete local preview of destination titles and wikitext. Headers
use descriptive titles, inherited work metadata, and previous/next links
derived from the edited reading order. Include `{{ppb}}` and the appropriate
`<pages>` selection. Render containers with child links, and render child
links alongside any parent introduction. Retain tree order for reading
order; define container participation explicitly in the renderer.

Create subpages only; leave the supplied root page untouched. An editor can
later choose and rename an entry point, commonly the contents page.
The initial CLI creates new local page content. If a destination already
exists, report it and refuse replacement by default; `--force` explicitly
allows replacing that destination's local content with generated content.
This is a generation command, not a conflict-resolution or merge tool:
it need not compare generations, reconcile manual changes, or implement a
separate update workflow. Preflight destination collisions before writing,
and report any partial failures with the affected destinations.

Generated content enters the normal editing, edit journal, and commit
workflow, where users handle subsequent changes and updates. Forced
replacement must also go through that workflow rather than bypassing its
history. Applying a proposal does not itself publish to the remote wiki;
`--force` concerns local generation and does not override commit-time
concurrency checks.

Later, add generation of the Index's `Page` attribute from the same work
representation, sharing scan labels and section boundaries with the Book
page renderer. This is an additional output target, not an obligation for
the initial subpage command to merge or maintain existing Index content.

## Labels and source adapters

Separate three concepts: physical scan number, printed page label, and
structural title. Labels may be roman, Arabic, literal text, repeated, or
unknown; they cannot be used as unique page identifiers.

For an existing Index, its effective pagelist is authoritative for displayed
labels. Reuse the locator computation and its explicit/inferred/unknown
confidence. PDF labels seed a proposal or supply provisional information
when an Index mapping is unavailable; expose their provenance and conflicts
instead of replacing an edited Index mapping. An Index with no outline
still gets a labelled flat view. Unknown labels retain the scan number.

PDF adapters preserve bookmark hierarchy and physical destinations. EPUB
adapters treat the spine as reading order and navigation documents as
hierarchy; they are complementary, not interchangeable. EPUB anchors such
as resource href plus fragment do not automatically identify scans. Until
an explicit mapping to an Index's scans exists, the outline can support
logical navigation but cannot generate scan-based `<pages>` ranges.
Manual YAML can supply either an outline with source anchors or a complete
transclusion proposal; distinguish those document kinds explicitly.

## API and IntelliJ VFS presentation

Expose a backend-owned, versioned work-navigation read model associated
with a site and Index. Exact route names remain to be chosen alongside the
existing locator API. It should include:

- Index identity, source identity/fingerprint, structure availability,
  revision token, and diagnostics about stale or unresolved mappings.
- Ordered nested outline nodes with stable opaque IDs, descriptive titles,
  optional type/number, source anchors, and mapped scan extents where known.
- Scan entries with scan number, canonical Page title/VFS path, effective
  printed label and confidence/provenance, and related outline node IDs.
- Distinct availability for known scans and locally cached Page content;
  missing cache entries must not disappear from the work's structure.

Node IDs are scoped to the stored outline and persist across title/path
edits; scan identities remain tied to the existing Index/file mapping.
Represent scan membership as potentially multiple nodes at a shared boundary.
Do not assume nested extents are disjoint: an ancestor's navigation extent
includes its descendants, unlike its own transclusion selection.

Allow clients to fetch structure and scan labels in batches, with pagination
or lazy child loading for large works. Reads use cached local data and do
not trigger extraction or remote fetching per VFS row. Revision tokens must
change when either the effective pagelist or stored structure changes so
clients can invalidate their presentation caches.

The plugin can offer a flat labelled view and an optional structured view.
A row might show `32 — p. 9 — The Leibowitz Challenge`; grouping can show
Part 1 → Chapter 1 → Section 1. Opening any scan resolves to its existing
canonical Page file. Display labels and grouping nodes must not rename
VirtualFiles, alter URLs, create wiki directories, or change save targets.
Keep a stable flat fallback when structure is absent, stale, or disabled.

The VFS view navigates source scans, not generated Book subpages. It remains
useful before any transclusion pages exist and can show finer structure
than the generation depth chosen for publication.

## Persistence and implementation boundaries

Store the imported/editorial outline as a versioned document associated
with the Index and source fingerprint. Keep the editable proposal as a
separate artifact referencing that source. The exact database layout and
outline upload/edit routes remain an implementation decision. Derived
labels and navigation extents are caches, not additional editorial truth.

A changed source fingerprint invalidates scan mappings until reviewed;
label edits alone invalidate labels without discarding structural edits.
Prefer typed Python domain classes and Pydantic API/document models over
dict-based data passing. Keep adapters, range planning, validation, wikitext
rendering, persistence, and API projection separate so each can evolve.

## Suggested delivery and verification

1. Preserve raw PDF structure and introduce typed/versioned YAML models.
2. Generate editable proposals with naming rules, depth, and diagnostics.
3. Validate and preview proposals, then generate new local pages through the
   edit workflow, with explicit forced replacement where requested.
4. Persist source structure and expose navigation alongside existing labels.
5. Add optional plugin labels/grouping; add EPUB mapping as a later adapter.

Add the Index `Page` attribute output target as a follow-on to proposal and
Book page generation, reusing the shared representation.

Verify with small fixtures covering front/back matter, continuous chapter
numbers, absent outlines, NUL-padded headings, empty parents, same-scan
boundaries, leading/trailing scans, and malformed destinations. Check that
depth reduction preserves scan coverage and parent path edits update all
resolved descendants. Round-trip edited YAML without losing decisions.
Check pagelist label changes invalidate navigation, missing cached pages
remain represented, and grouped navigation opens the same canonical file
and save target as the flat view when those features are implemented.
The initial implementation tests proposal coverage, naming and depth,
YAML edits, preview, destination preflight, journal integration, and rollback.
