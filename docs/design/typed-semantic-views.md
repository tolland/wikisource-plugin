# Typed semantic views prototype

The grammar describes generic tag structure. `WtHtmlTag` remains the real PSI
node for both `<ref>` and `<section>`; neither has a dedicated AST element type.
`WtSemanticViews` interprets a tag and returns a typed, transient view:

```kotlin
when (val view = WtSemanticViews.of(element)) {
    is WtReferenceView -> {
        val sourcePsi = view.source
        val name = view.name
        val bodyRange = view.bodyRange
    }
    is WtSectionMarkerView -> {
        val label = view.name
        val boundary = view.boundary // BEGIN or END
    }
    null -> Unit // ordinary syntax, unsupported or ambiguous semantics
}
```

`WtTagView` exposes opening/closing/body ranges and attributes with exact value
ranges. Those ranges are absolute document offsets. The attribute reader accepts
quoted and simple unquoted values; it is tolerant source extraction, not a full
implementation of MediaWiki's extension-specific attribute interpretation.

Reference highlighting and exclusion from document sentence bands now consume
these views. Highlighting options and visual styling are unchanged. Self-closing
references are represented as reuse forms, even if incomplete or unnamed; the
factory classifies source and does not validate its meaning.

Section begin/end views represent individual source markers. They do not pair
markers, create spans, or diagnose unmatched labels. Overlapping sections would
be separate derived records with links to their source markers. This prototype
does not assume what MediaWiki does with unmatched markers. Anchors, transclusion
and image semantics are not implemented yet; they can have views over their
existing template or link PSI when required.

## IntelliJ integration boundary

Views are not PSI nodes. IntelliJ does not see `WtReferenceView` in PSI visitors,
class-based extension patterns, or stub indexes. Feature code must classify a
source PSI element at its entry point:

| Feature | Integration |
| --- | --- |
| Annotators, inspections, folding | Match generic PSI, classify, use view ranges. Reference highlighting demonstrates this. |
| Navigation and references | A `PsiReference` adapter must be attached to source PSI; `resolve()` returns target PSI, not a view. No such adapter is registered in this prototype. |
| Rename / Find Usages | Need the platform reference hooks and a suitable named target or explicit rename integration. Wrappers alone do not supply these. |
| Stub indexing | Need an explicit generic-tag stub schema or another index. Views do not acquire stubs automatically. |
| SQLite / API | Extract immutable domain records from views; do not persist PSI or wrapper instances. |

Use a view only during the current PSI read pass. It contains a source snapshot
and may become stale after edits. Retain a `SmartPsiElementPointer` to its source
if needed, then classify again after resolving that pointer. The editing test
changes `<ref>` to `<span>` and back through a document and confirms that the
same generic node type and a smart pointer support reclassification.

The tradeoff is explicit: fewer grammar/PSI types, but semantic consumers need a
classification call. Specialised PSI could expose types directly to platform
patterns and visitors, although reference resolution and indexing would still
need implementations in either design.
