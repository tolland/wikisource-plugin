package org.limepepper.lang.wikitext.editing

import org.limepepper.lang.wikitext.lexer.WtLexerAdapter
import org.limepepper.lang.wikitext.psi.WtTypes
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * Guards the one piece of knowledge this codebase holds twice: how many
 * apostrophes of a run are markup.
 *
 * `WtLexer.apostropheRun()` (generated Java, from `WikitextLexer.flex`) and
 * [WtQuoteScanner.markerLengthFor] (Kotlin, used by the editor actions and any
 * renderer) implement the same MediaWiki rule independently, because the
 * generated lexer cannot call into Kotlin. If they ever drift, bold text would
 * highlight one way and toggle another — so assert they agree instead of
 * hoping.
 */
class WtQuoteLexerAgreementTest {

    private val apostropheTokens = mapOf(
        WtTypes.TWO_APOS to 2,
        WtTypes.THREE_APOS to 3,
        WtTypes.FIVE_APOS to 5,
    )

    /** The marker length the lexer assigns to a run of [runLength] apostrophes. */
    private fun lexerMarkerLength(runLength: Int): Int {
        val lexer = WtLexerAdapter()
        val text = "x" + "'".repeat(runLength) + "y"
        lexer.start(text)
        var lastMarkerLength = 0
        while (lexer.tokenType != null) {
            val length = apostropheTokens[lexer.tokenType]
            if (length != null) {
                assertEquals(
                    length,
                    lexer.tokenEnd - lexer.tokenStart,
                    "token ${lexer.tokenType} did not cover $length characters",
                )
                lastMarkerLength = length
            }
            lexer.advance()
        }
        return lastMarkerLength
    }

    @Test
    fun lexerAndScannerAgreeOnEveryRunLength() {
        // 1 is excluded: the lexer emits SINGLE_APOS for it (a literal
        // apostrophe is still a token), while the scanner reports 0 markup
        // characters. Both mean "not markup".
        for (runLength in 2..10) {
            assertEquals(
                WtQuoteScanner.markerLengthFor(runLength),
                lexerMarkerLength(runLength),
                "run of $runLength apostrophes",
            )
        }
    }

    @Test
    fun loneApostropheIsMarkupToNeither() {
        assertEquals(0, WtQuoteScanner.markerLengthFor(1))
        assertEquals(0, lexerMarkerLength(1))
    }
}
