package org.limepepper.lang.wikitext.editing

import kotlin.test.Test
import kotlin.test.assertEquals

class WtQuoteScannerTest {

    // ---- run length -> marker length ------------------------------------

    @Test
    fun markerLengthMatchesMediaWikiRunRules() {
        // The same table WtLexer.apostropheRun() implements; kept in step by
        // WtQuoteLexerAgreementTest.
        assertEquals(
            mapOf(1 to 0, 2 to 2, 3 to 3, 4 to 3, 5 to 5, 6 to 5, 7 to 5, 8 to 5),
            WtQuoteScanner.markerLengthTable,
        )
    }

    @Test
    fun literalApostrophesSitAtTheFrontOfARun() {
        // "''''x" is a literal quote then bold, so the marker starts one in.
        val marker = WtQuoteScanner.markers("''''x").single()
        assertEquals(0, marker.runStart)
        assertEquals(1, marker.start)
        assertEquals(4, marker.end)
        assertEquals(3, marker.length)
    }

    @Test
    fun loneApostrophesAreNotMarkers() {
        assertEquals(emptyList(), WtQuoteScanner.markers("don't stop"))
    }

    // ---- active styles ---------------------------------------------------

    @Test
    fun stylesAtTracksToggling() {
        val line = "a '''b''' c"
        assertEquals(emptySet(), WtQuoteScanner.stylesAt(line, 0))
        assertEquals(setOf(WtQuoteStyle.BOLD), WtQuoteScanner.stylesAt(line, line.indexOf('b')))
        assertEquals(emptySet(), WtQuoteScanner.stylesAt(line, line.length))
    }

    @Test
    fun fiveRunTogglesBothStyles() {
        val line = "'''''x'''''"
        assertEquals(
            setOf(WtQuoteStyle.BOLD, WtQuoteStyle.ITALIC),
            WtQuoteScanner.stylesAt(line, line.indexOf('x')),
        )
    }

    @Test
    fun stylesCanOverlapPartially() {
        // Bold opens, italic opens inside it, bold closes first.
        val line = "'''a''b''' c''"
        assertEquals(setOf(WtQuoteStyle.BOLD), WtQuoteScanner.stylesAt(line, line.indexOf('a')))
        assertEquals(
            setOf(WtQuoteStyle.BOLD, WtQuoteStyle.ITALIC),
            WtQuoteScanner.stylesAt(line, line.indexOf('b')),
        )
        assertEquals(setOf(WtQuoteStyle.ITALIC), WtQuoteScanner.stylesAt(line, line.indexOf('c')))
    }

    // ---- spans, for renderers -------------------------------------------

    @Test
    fun styledSpansCoverContentNotMarkers() {
        val line = "a '''bold''' b"
        assertEquals(
            listOf(WtQuoteSpan(line.indexOf("bold"), line.indexOf("bold") + 4, WtQuoteStyle.BOLD)),
            WtQuoteScanner.styledSpans(line),
        )
    }

    @Test
    fun unclosedSpanRunsToEndOfLine() {
        val line = "a '''bold"
        assertEquals(
            listOf(WtQuoteSpan(line.indexOf("bold"), line.length, WtQuoteStyle.BOLD)),
            WtQuoteScanner.styledSpans(line),
        )
    }

    @Test
    fun fiveRunProducesBothSpans() {
        val line = "'''''x'''''"
        val spans = WtQuoteScanner.styledSpans(line)
        assertEquals(setOf(WtQuoteStyle.BOLD, WtQuoteStyle.ITALIC), spans.map { it.style }.toSet())
        for (span in spans) {
            assertEquals("x", line.substring(span.start, span.end))
        }
    }

    @Test
    fun emptyRunsProduceNoSpans() {
        assertEquals(emptyList(), WtQuoteScanner.styledSpans("''''''''''"))
    }
}
