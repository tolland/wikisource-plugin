package org.limepepper.lang.wikitext.tags

/**
 * Structural classification of a tag for [org.limepepper.lang.wikitext.structure.WtStructureViewFactory]
 * purposes -- i.e. "should this tag's content be shown as its own
 * block-level node in the outline, or treated as part of the surrounding
 * paragraph flow."
 *
 * This is DELIBERATELY separate from lexing/parsing: a tag's block-vs-inline
 * rendering behavior is determined by either (a) fixed HTML/CSS semantics
 * for the standard allowlisted tags, which is static and knowable, or
 * (b) MediaWiki/ProofreadPage extension semantics for parser tags, which
 * we hand-curate below -- NOT by anything in the PSI tree itself. Crucially,
 * this table does NOT cover MediaWiki TEMPLATES ({{...}}) -- a template's
 * block/inline rendering is determined by Lua module code installed on a
 * specific wiki and can differ between wikis for the identical template
 * name (e.g. {{ph}} renders as a block div on Wikisource but an inline
 * span on Wikipedia). There is no syntactic signal for that; do not try to
 * extend this table to templates. See project discussion.
 */
enum class WtTagDisplayKind {
    /** Generates a block-level box (div, p, table, list containers, etc). */
    BLOCK,

    /** Generates an inline box (span, code, em, etc) -- part of the text flow. */
    INLINE,

    /**
     * Generates NO visual box of its own under normal rendering -- either
     * because it's a parse-time instruction (nowiki suppresses parsing of
     * its content; noinclude/includeonly/onlyinclude control what gets
     * transcluded where) or because it's a ProofreadPage/extension
     * structural marker with no inherent CSS box (pagelist renders a grid
     * widget on Index pages only, not content; section markers are
     * typically invisible transclusion boundaries; pages is a
     * transclusion instruction, not a rendered element).
     *
     * For structure-view purposes, TRANSPARENT tags are usually still
     * worth showing as their own outline node (they're structurally
     * significant even without a CSS box), just not classified as
     * block-or-inline.
     */
    TRANSPARENT,

    /**
     * We don't have a curated answer for this tag name. The structure
     * view should show it honestly as an unclassified node (e.g. "Tag:
     * foo") rather than guessing block or inline -- consistent with the
     * project's fail-fast/no-silent-guessing philosophy.
     */
    UNKNOWN
}

object WtTagDisplayClassifier {

    // ------------------------------------------------------------------
    // Standard MediaWiki-allowlisted HTML passthrough tags. This list and
    // the block/inline split are ordinary, well-established HTML/CSS
    // default-display semantics -- nothing wiki-specific to guess here.
    // Source for the allowlist itself: MediaWiki's Sanitizer/Help:HTML in
    // wikitext "most safe HTML tags" list (b, del, i, ins, u, font, big,
    // small, sub, sup, h1-h6, cite, code, div, center, blockquote, ol, ul,
    // dl, table, caption, pre, ruby, rt, rb, rp, p, span, br, hr, li, dt,
    // dd, td, th, tr, em, s, strike, strong, tt, var).
    // ------------------------------------------------------------------

    private val HTML_BLOCK = setOf(
        "div", "p", "table", "caption", "blockquote", "center",
        "ol", "ul", "dl", "li", "dt", "dd",
        "tr", "td", "th",
        "pre", // block per CSS default, though content is unparsed wikitext
        "h1", "h2", "h3", "h4", "h5", "h6",
        "hr"
    )

    private val HTML_INLINE = setOf(
        "span", "code", "cite", "em", "strong", "b", "i", "u",
        "s", "strike", "del", "ins", "tt", "var", "font",
        "big", "small", "sub", "sup",
        "ruby", "rt", "rb", "rp",
        "br" // technically inline-replaced, no box of its own, but lives in text flow
    )

    // ------------------------------------------------------------------
    // Tags that suppress or redirect parsing -- no visual box of their
    // own under normal page rendering. nowiki specifically: confirmed via
    // MediaWiki docs that its content is "not parsed, as in a pre tag" --
    // but unlike <pre>, nowiki produces no visible wrapper element either;
    // it's purely a parse-time escape.
    // ------------------------------------------------------------------

    private val PARSER_CONTROL_TAGS = setOf(
        "nowiki", "noinclude", "includeonly", "onlyinclude"
    )

    // ------------------------------------------------------------------
    // Always-assumed infrastructure for this project (per project
    // decision: code/math support is assumed present on the target wiki,
    // not optional). Confirmed via live MediaWiki render trace: math
    // renders as <span class="mwe-math-element-inline">...</span> by
    // default (display-mode math would need explicit \[ \] / :<math> block
    // styling, which this project doesn't currently special-case).
    // ------------------------------------------------------------------

    private val ALWAYS_AVAILABLE_INLINE = setOf("math")
    // "code" is already covered by HTML_INLINE above.

    // ------------------------------------------------------------------
    // ProofreadPage / Labeled Section Transclusion extension tags.
    // VERIFIED via MediaWiki/Wikisource documentation (see citations in
    // project discussion) rather than assumed:
    //   - <pages .../>  : transclusion INSTRUCTION (Help:Extension:
    //     ProofreadPage/Pages tag) -- not a rendered box.
    //   - <pagelist/>   : displays a page-number grid WIDGET on Index
    //     pages only; explicitly confirmed "pagelist does not output a
    //     table" (Wikisource talk:ProofreadPage) -- no box on rendered
    //     main-namespace content.
    //   - <section begin="x"/> / <section end="x"/> : Labeled Section
    //     Transclusion boundary markers, normally invisible.
    // NOTE: there is no <page> (singular) tag -- only <pages> (plural,
    // for transclusion) and the "Page:" namespace (a page TYPE, not a
    // tag). Don't confuse the two.
    // ------------------------------------------------------------------

    private val PROOFREAD_PAGE_TAGS = setOf("pages", "pagelist", "section")

    fun classify(tagName: String): WtTagDisplayKind {
        val name = tagName.lowercase()
        return when {
            name in HTML_BLOCK -> WtTagDisplayKind.BLOCK
            name in HTML_INLINE -> WtTagDisplayKind.INLINE
            name in ALWAYS_AVAILABLE_INLINE -> WtTagDisplayKind.INLINE
            name in PARSER_CONTROL_TAGS -> WtTagDisplayKind.TRANSPARENT
            name in PROOFREAD_PAGE_TAGS -> WtTagDisplayKind.TRANSPARENT
            else -> WtTagDisplayKind.UNKNOWN
        }
    }
}
