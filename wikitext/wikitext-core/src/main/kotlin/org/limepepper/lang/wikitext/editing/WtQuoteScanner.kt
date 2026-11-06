package org.limepepper.lang.wikitext.editing

/**
 * The two quote styles MediaWiki expresses with apostrophe runs.
 *
 * A run of five means *both*, which is why this is a pair of independent
 * styles rather than a three-valued enum: `'''''x'''''` is bold and italic at
 * once, and removing one has to leave the other behind.
 */
enum class WtQuoteStyle(val markerLength: Int) {
    ITALIC(2),
    BOLD(3),
    ;

    /** The literal marker text, e.g. `'''` for [BOLD]. */
    val marker: String = "'".repeat(markerLength)
}

/**
 * One apostrophe run's *markup* portion.
 *
 * [runStart] is where the raw run of apostrophes begins; [start] is where its
 * marker begins. They differ when MediaWiki treats leading apostrophes of the
 * run as literal text — see [WtQuoteScanner.markerLengthFor].
 */
data class WtQuoteMarker(
    val runStart: Int,
    val start: Int,
    val end: Int,
) {
    val length: Int get() = end - start

    /** True when this marker turns [style] on or off. */
    fun affects(style: WtQuoteStyle): Boolean =
        length == WtQuoteScanner.BOTH_LENGTH || length == style.markerLength
}

/**
 * Finds quote markup in a single line of wikitext.
 *
 * Single line is not a simplification — MediaWiki's own rule is that "italic
 * and bold formatting works correctly only within a single line", so a line is
 * exactly the scope in which runs pair up. That is what makes this tractable
 * without a full parser pass, and why the toggle actions can work off it.
 *
 * The scanner deliberately does NOT try to resolve the five-run nesting
 * ambiguity (see `WtLexer.apostropheRun`): it reports which styles are toggled
 * where, which is all a toggle action or a highlighter needs. Whether
 * `'''''x'' y'''` nested bold-outside or italic-outside changes the rendered
 * tree but not which characters are bold and which are italic.
 */
object WtQuoteScanner {

    /** Marker length meaning "bold and italic at once". */
    const val BOTH_LENGTH: Int = 5

    /**
     * How many of a run's [runLength] apostrophes are markup, per MediaWiki.
     * The excess is literal text and sits at the *front* of the run.
     *
     * Mirrors `WtLexer.apostropheRun()` in `WikitextLexer.flex`; the two are
     * separate because the lexer is generated Java and this is Kotlin, so
     * [markerLengthTable] is asserted against the lexer's behaviour in tests
     * rather than shared by construction.
     */
    fun markerLengthFor(runLength: Int): Int = when {
        runLength <= 1 -> 0                 // a lone apostrophe is never markup
        runLength <= 3 -> runLength         // 2 = italic, 3 = bold
        runLength == 4 -> 3                 // one literal apostrophe, then bold
        else -> BOTH_LENGTH                 // 5, or 5 with literal apostrophes ahead of it
    }

    /** The documented length table, for tests and for reading. */
    val markerLengthTable: Map<Int, Int>
        get() = (1..8).associateWith { markerLengthFor(it) }

    /** Every quote marker on [line], in document order. */
    fun markers(line: CharSequence): List<WtQuoteMarker> {
        val found = mutableListOf<WtQuoteMarker>()
        var i = 0
        while (i < line.length) {
            if (line[i] != '\'') {
                i++
                continue
            }
            val runStart = i
            while (i < line.length && line[i] == '\'') i++
            val markerLength = markerLengthFor(i - runStart)
            if (markerLength > 0) {
                found += WtQuoteMarker(runStart = runStart, start = i - markerLength, end = i)
            }
        }
        return found
    }

    /**
     * The styles in effect at [offset] (line-relative), determined by walking
     * every marker that has *closed* before it. A marker exactly ending at
     * [offset] counts as applied, so the offset just after `'''` is bold.
     */
    fun stylesAt(line: CharSequence, offset: Int): Set<WtQuoteStyle> =
        stylesAfter(markers(line).filter { it.end <= offset })

    /** Styles left active once [markers] have each toggled what they affect. */
    fun stylesAfter(markers: List<WtQuoteMarker>): Set<WtQuoteStyle> {
        val active = mutableSetOf<WtQuoteStyle>()
        for (marker in markers) {
            for (style in WtQuoteStyle.entries) {
                if (marker.affects(style)) {
                    if (!active.add(style)) active.remove(style)
                }
            }
        }
        return active
    }

    /**
     * The spans of [line] over which each style is in effect, for renderers
     * that want to show bold text as actually bold.
     *
     * An unclosed run runs to end of line, which is what MediaWiki does too.
     * Spans cover the *content*, not the markers.
     */
    fun styledSpans(line: CharSequence): List<WtQuoteSpan> {
        val spans = mutableListOf<WtQuoteSpan>()
        val openedAt = mutableMapOf<WtQuoteStyle, Int>()
        for (marker in markers(line)) {
            for (style in WtQuoteStyle.entries) {
                if (!marker.affects(style)) continue
                val open = openedAt.remove(style)
                if (open == null) {
                    openedAt[style] = marker.end
                } else if (marker.start > open) {
                    spans += WtQuoteSpan(open, marker.start, style)
                }
            }
        }
        for ((style, open) in openedAt) {
            if (line.length > open) spans += WtQuoteSpan(open, line.length, style)
        }
        return spans.sortedWith(compareBy({ it.start }, { it.style }))
    }
}

/** A run of text over which one [WtQuoteStyle] applies. */
data class WtQuoteSpan(val start: Int, val end: Int, val style: WtQuoteStyle)
