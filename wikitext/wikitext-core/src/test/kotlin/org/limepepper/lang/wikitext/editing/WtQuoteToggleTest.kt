package org.limepepper.lang.wikitext.editing

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * The Ctrl+B / Ctrl+I logic. Pure text in, pure text out — the IDE action is
 * a thin shell over this, so these cases are the real specification.
 */
class WtQuoteToggleTest {

    /** Applies a toggle to a single-line document and returns the new text. */
    private fun toggle(text: String, style: WtQuoteStyle, from: Int, to: Int): String {
        val result = WtQuoteToggle.toggleLine(text, 0, from, to, style)
        val builder = StringBuilder(text)
        for (edit in result.edits.sortedByDescending { it.start }) {
            builder.replace(edit.start, edit.end, edit.replacement)
        }
        return builder.toString()
    }

    /** Toggle over the (first) occurrence of [word]. */
    private fun toggleWord(text: String, style: WtQuoteStyle, word: String): String {
        val from = text.indexOf(word)
        require(from >= 0) { "no '$word' in '$text'" }
        return toggle(text, style, from, from + word.length)
    }

    // ---- adding ---------------------------------------------------------

    @Test
    fun addsBoldAroundSelection() {
        assertEquals("a '''word''' b", toggleWord("a word b", WtQuoteStyle.BOLD, "word"))
    }

    @Test
    fun addsItalicAroundSelection() {
        assertEquals("a ''word'' b", toggleWord("a word b", WtQuoteStyle.ITALIC, "word"))
    }

    @Test
    fun addingWithNoSelectionInsertsAnEmptyPairAndCaretsBetween() {
        val result = WtQuoteToggle.toggleLine("ab", 0, 1, 1, WtQuoteStyle.BOLD)
        assertEquals("a''''''b", toggle("ab", WtQuoteStyle.BOLD, 1, 1))
        // Caret sits between the markers, ready to type.
        assertEquals(4, result.selectionStart)
        assertEquals(4, result.selectionEnd)
    }

    @Test
    fun addingKeepsTheSameTextSelected() {
        val text = "a word b"
        val from = text.indexOf("word")
        val result = WtQuoteToggle.toggleLine(text, 0, from, from + 4, WtQuoteStyle.BOLD)
        val after = toggle(text, WtQuoteStyle.BOLD, from, from + 4)
        assertEquals("word", after.substring(result.selectionStart, result.selectionEnd))
    }

    // ---- removing -------------------------------------------------------

    @Test
    fun removesBoldWhenAlreadyBold() {
        assertEquals("a word b", toggleWord("a '''word''' b", WtQuoteStyle.BOLD, "word"))
    }

    @Test
    fun removesItalicWhenAlreadyItalic() {
        assertEquals("a word b", toggleWord("a ''word'' b", WtQuoteStyle.ITALIC, "word"))
    }

    @Test
    fun removingKeepsTheSameTextSelected() {
        val text = "a '''word''' b"
        val from = text.indexOf("word")
        val result = WtQuoteToggle.toggleLine(text, 0, from, from + 4, WtQuoteStyle.BOLD)
        val after = toggle(text, WtQuoteStyle.BOLD, from, from + 4)
        assertEquals("word", after.substring(result.selectionStart, result.selectionEnd))
    }

    // ---- the five-run cases, which are the whole reason for run-length editing

    @Test
    fun removingBoldFromBoldItalicLeavesItalic() {
        assertEquals("a ''word'' b", toggleWord("a '''''word''''' b", WtQuoteStyle.BOLD, "word"))
    }

    @Test
    fun removingItalicFromBoldItalicLeavesBold() {
        assertEquals("a '''word''' b", toggleWord("a '''''word''''' b", WtQuoteStyle.ITALIC, "word"))
    }

    @Test
    fun addingItalicToBoldProducesTheFiveRun() {
        assertEquals("a '''''word''''' b", toggleWord("a '''word''' b", WtQuoteStyle.ITALIC, "word"))
    }

    @Test
    fun addingBoldToItalicProducesTheFiveRun() {
        assertEquals("a '''''word''''' b", toggleWord("a ''word'' b", WtQuoteStyle.BOLD, "word"))
    }

    // ---- awkward but legal input ---------------------------------------

    @Test
    fun unclosedRunStillTogglesOff() {
        // Only an opener exists; removing it is better than refusing to act.
        assertEquals("a word b", toggleWord("a '''word b", WtQuoteStyle.BOLD, "word"))
    }

    @Test
    fun contractionsAreNotTreatedAsMarkup() {
        // A lone apostrophe is never markup, so this is a plain add.
        assertEquals("it's '''a''' test", toggleWord("it's a test", WtQuoteStyle.BOLD, "a"))
    }

    @Test
    fun literalApostropheBeforeBoldIsPreserved() {
        // "''''" is one literal apostrophe + bold; un-bolding must leave the
        // literal apostrophe alone.
        assertEquals("a 'word' b", toggleWord("a ''''word'''' b", WtQuoteStyle.BOLD, "word"))
    }

    // ---- multi-line -----------------------------------------------------

    @Test
    fun multiLineSelectionTogglesEachLineSeparately() {
        // MediaWiki quote markup does not cross a newline, so a paragraph
        // selection has to be wrapped per line rather than once overall.
        val text = "one\ntwo"
        val lines = listOf(0..2, 4..6)
        val result = WtQuoteToggle.toggleRange(text, lines, 0, text.length, WtQuoteStyle.BOLD)
        val builder = StringBuilder(text)
        for (edit in result.edits) builder.replace(edit.start, edit.end, edit.replacement)
        assertEquals("'''one'''\n'''two'''", builder.toString())
    }

    @Test
    fun multiLineEditsComeBackInDescendingOrder() {
        val text = "one\ntwo"
        val result = WtQuoteToggle.toggleRange(text, listOf(0..2, 4..6), 0, text.length, WtQuoteStyle.BOLD)
        val starts = result.edits.map { it.start }
        assertEquals(starts.sortedDescending(), starts)
    }

    @Test
    fun blankLinesInASelectionAreSkipped() {
        val text = "one\n\ntwo"
        val result = WtQuoteToggle.toggleRange(text, listOf(0..2, 4..3, 5..7), 0, text.length, WtQuoteStyle.BOLD)
        val builder = StringBuilder(text)
        for (edit in result.edits) builder.replace(edit.start, edit.end, edit.replacement)
        assertEquals("'''one'''\n\n'''two'''", builder.toString())
    }

    @Test
    fun togglingIsItsOwnInverse() {
        for (style in WtQuoteStyle.entries) {
            val original = "a word b"
            val once = toggleWord(original, style, "word")
            assertTrue(once != original, "$style did nothing")
            assertEquals(original, toggleWord(once, style, "word"), "$style did not round-trip")
        }
    }
}
