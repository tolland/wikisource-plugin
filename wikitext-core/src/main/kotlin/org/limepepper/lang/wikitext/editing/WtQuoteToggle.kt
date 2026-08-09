package org.limepepper.lang.wikitext.editing

/** A replacement of `[start, end)` with [replacement], in document offsets. */
data class WtTextEdit(val start: Int, val end: Int, val replacement: String) {
    val lengthDelta: Int get() = replacement.length - (end - start)
}

/** Edits to apply, plus where the selection should land afterwards. */
data class WtQuoteToggleResult(
    val edits: List<WtTextEdit>,
    val selectionStart: Int,
    val selectionEnd: Int,
) {
    val isEmpty: Boolean get() = edits.isEmpty()
}

/**
 * Adds or removes a [WtQuoteStyle] around a selection — the logic behind
 * Ctrl+B / Ctrl+I.
 *
 * ## Why this edits run *lengths* rather than whole markers
 *
 * The obvious implementation — "delete the `'''` before and after" — is wrong
 * for the five-run case. Un-bolding `'''''x'''''` must leave `''x''`, and
 * un-italicising it must leave `'''x'''`. So removal shrinks a marker by the
 * style's own length and only deletes it when nothing is left. That one rule
 * covers every combination, which is why there is no special case for "both".
 *
 * Everything is line-scoped, following MediaWiki's rule that quote formatting
 * only works within a single line; a multi-line selection is toggled line by
 * line (see [toggleRange]).
 */
object WtQuoteToggle {

    /**
     * An edit plus which ends of the selection it drags along with it.
     *
     * Offsets alone cannot answer this. When the caret is empty both the
     * opening and closing markers are inserted at the very same offset, and
     * only the opener should push the caret rightwards — otherwise pressing
     * Ctrl+B on an empty selection lands the caret after the closing marker
     * instead of between the two, which is precisely where you want to type.
     */
    private class PlacedEdit(val edit: WtTextEdit, val shiftsStart: Boolean, val shiftsEnd: Boolean)

    /**
     * Toggles [style] over `[selectionStart, selectionEnd)` of a single line.
     *
     * [lineStart] is the line's document offset; every offset in and out of
     * this function is a document offset, so callers never juggle two
     * coordinate systems.
     */
    fun toggleLine(
        line: CharSequence,
        lineStart: Int,
        selectionStart: Int,
        selectionEnd: Int,
        style: WtQuoteStyle,
    ): WtQuoteToggleResult = assemble(
        placedEdits(line, lineStart, selectionStart, selectionEnd, style),
        selectionStart,
        selectionEnd,
    )

    /**
     * Toggles [style] across a document range that may span lines, applying
     * the single-line rule to each line's intersection with the range.
     *
     * Lines whose intersection is blank are skipped: wrapping whitespace in
     * quote markers only produces stray apostrophes on the rendered page.
     */
    fun toggleRange(
        text: CharSequence,
        lines: List<IntRange>,
        selectionStart: Int,
        selectionEnd: Int,
        style: WtQuoteStyle,
    ): WtQuoteToggleResult {
        val placed = mutableListOf<PlacedEdit>()
        for (line in lines) {
            val lineEnd = line.last + 1
            val from = maxOf(selectionStart, line.first)
            val to = minOf(selectionEnd, lineEnd)
            if (from >= to && !(from == to && lines.size == 1)) continue
            if (from < to && text.subSequence(from, to).isBlank()) continue
            placed += placedEdits(text.subSequence(line.first, lineEnd), line.first, from, to, style)
        }
        return assemble(placed, selectionStart, selectionEnd)
    }

    /** Sorts edits for safe application and works out where the selection goes. */
    private fun assemble(
        placed: List<PlacedEdit>,
        selectionStart: Int,
        selectionEnd: Int,
    ): WtQuoteToggleResult {
        var startShift = 0
        var endShift = 0
        for (item in placed) {
            if (item.shiftsStart) startShift += item.edit.lengthDelta
            if (item.shiftsEnd) endShift += item.edit.lengthDelta
        }
        // Descending, so applying each replacement leaves earlier offsets valid.
        val edits = placed.map { it.edit }.sortedByDescending { it.start }
        return WtQuoteToggleResult(edits, selectionStart + startShift, selectionEnd + endShift)
    }

    private fun placedEdits(
        line: CharSequence,
        lineStart: Int,
        selectionStart: Int,
        selectionEnd: Int,
        style: WtQuoteStyle,
    ): List<PlacedEdit> {
        val start = (selectionStart - lineStart).coerceIn(0, line.length)
        val end = (selectionEnd - lineStart).coerceIn(start, line.length)
        val markers = WtQuoteScanner.markers(line)

        // The selection may itself contain the markers -- that is what you get
        // by double-clicking a bolded word and dragging over the quotes, and
        // treating it as "not yet bold" would add a second layer of markup.
        val wrappingOpener = markers.firstOrNull { it.start == start && it.affects(style) }
        val wrappingCloser = markers.lastOrNull { it.end == end && it.affects(style) }
        if (wrappingOpener != null && wrappingCloser != null && wrappingOpener != wrappingCloser) {
            return listOf(
                // The selection keeps its left edge and loses both markers, so
                // only its end moves.
                PlacedEdit(shrink(wrappingOpener, style, lineStart), shiftsStart = false, shiftsEnd = true),
                PlacedEdit(shrink(wrappingCloser, style, lineStart), shiftsStart = false, shiftsEnd = true),
            )
        }

        val active = style in WtQuoteScanner.stylesAfter(markers.filter { it.end <= start })
        return if (active) removeEdits(markers, start, end, style, lineStart) else addEdits(start, end, style, lineStart)
    }

    /**
     * Shrinks the markers that turned [style] on before the selection and off
     * after it. A missing closer (an unclosed run, which is legal and common
     * in real wikitext) just means only the opener is edited — better than
     * refusing to act.
     */
    private fun removeEdits(
        markers: List<WtQuoteMarker>,
        start: Int,
        end: Int,
        style: WtQuoteStyle,
        lineStart: Int,
    ): List<PlacedEdit> {
        val opener = markers.lastOrNull { it.end <= start && it.affects(style) }
        val closer = markers.firstOrNull { it.start >= end && it.affects(style) }
        return listOfNotNull(
            // Sits before the selection, so the whole selection slides left.
            opener?.let { PlacedEdit(shrink(it, style, lineStart), shiftsStart = true, shiftsEnd = true) },
            // Sits after the selection, so neither end moves.
            closer?.let { PlacedEdit(shrink(it, style, lineStart), shiftsStart = false, shiftsEnd = false) },
        )
    }

    /** Removes [style]'s apostrophes from one marker, deleting what is left over. */
    private fun shrink(marker: WtQuoteMarker, style: WtQuoteStyle, lineStart: Int): WtTextEdit {
        val remaining = (marker.length - style.markerLength).coerceAtLeast(0)
        return WtTextEdit(
            start = lineStart + marker.start,
            end = lineStart + marker.end,
            replacement = "'".repeat(remaining),
        )
    }

    private fun addEdits(start: Int, end: Int, style: WtQuoteStyle, lineStart: Int): List<PlacedEdit> = listOf(
        // Opening marker: pushes the selected text (and an empty caret) right.
        PlacedEdit(
            WtTextEdit(lineStart + start, lineStart + start, style.marker),
            shiftsStart = true,
            shiftsEnd = true,
        ),
        // Closing marker: lands after the selection, so it moves neither end.
        PlacedEdit(
            WtTextEdit(lineStart + end, lineStart + end, style.marker),
            shiftsStart = false,
            shiftsEnd = false,
        ),
    )
}
