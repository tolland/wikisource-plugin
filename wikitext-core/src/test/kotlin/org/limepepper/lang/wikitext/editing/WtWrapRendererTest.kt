package org.limepepper.lang.wikitext.editing

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * The markup half of the editing features, tested without an IDE fixture.
 *
 * Every surround implementation renders through [WtWrapRenderer], so these
 * cases pin the *output* once and leave the IDE-level tests free to be about
 * interaction only.
 */
class WtWrapRendererTest {

    // ---- inline tags ----------------------------------------------------

    @Test
    fun inlineTagWrapsWithoutAddingLines() {
        val rendering = WtWrapRenderer.render(WtWrapTag.CODE, "foo")
        assertEquals("<code>foo</code>", rendering.text)
        assertEquals("foo", rendering.text.substring(rendering.contentStart, rendering.contentEnd))
    }

    @Test
    fun quoteMarkersAreJustText() {
        assertEquals("'''foo'''", WtWrapRenderer.render(WtWrapTag.BOLD, "foo").text)
        assertEquals("''foo''", WtWrapRenderer.render(WtWrapTag.ITALIC, "foo").text)
    }

    @Test
    fun inlineTagHasNoVariables() {
        assertTrue(WtWrapRenderer.render(WtWrapTag.NOWIKI, "foo").variableRanges.isEmpty())
    }

    @Test
    fun emptySelectionStillProducesAWellFormedPair() {
        val rendering = WtWrapRenderer.render(WtWrapTag.REF, "")
        assertEquals("<ref></ref>", rendering.text)
        assertEquals(rendering.contentStart, rendering.contentEnd)
    }

    // ---- block tags -----------------------------------------------------

    @Test
    fun blockTagPutsMarkersOnTheirOwnLines() {
        val rendering = WtWrapRenderer.render(WtWrapTag.NOINCLUDE, "foo")
        assertEquals("<noinclude>\nfoo\n</noinclude>", rendering.text)
        assertEquals("foo", rendering.text.substring(rendering.contentStart, rendering.contentEnd))
    }

    @Test
    fun blockTagReusesTheLineIndent() {
        val rendering = WtWrapRenderer.render(WtWrapTag.POEM, "foo", indent = "  ")
        assertEquals("<poem>\n  foo\n  </poem>", rendering.text)
    }

    @Test
    fun multiLineSelectionIsPreservedVerbatim() {
        val rendering = WtWrapRenderer.render(WtWrapTag.PRE, "one\ntwo")
        assertEquals("<pre>\none\ntwo\n</pre>", rendering.text)
    }

    // ---- the variable case ----------------------------------------------

    @Test
    fun sectionKeepsPlaceholderAndReportsBothOccurrences() {
        val rendering = WtWrapRenderer.render(WtWrapTag.SECTION, "body")
        assertEquals(
            "<section begin=\"name\" />\nbody\n<section end=\"name\" />",
            rendering.text,
        )
        // Two mirrors, so a caller can keep begin and end in step.
        assertEquals(2, rendering.variableRanges.size)
        for (range in rendering.variableRanges) {
            assertEquals(
                WtWrapRenderer.DEFAULT_PLACEHOLDER,
                rendering.text.substring(range.first, range.last + 1),
            )
        }
    }

    @Test
    fun sectionSubstitutesASuppliedValueInBothMarkers() {
        val rendering = WtWrapRenderer.render(WtWrapTag.SECTION, "body", variableValue = "para-1")
        assertEquals(
            "<section begin=\"para-1\" />\nbody\n<section end=\"para-1\" />",
            rendering.text,
        )
        assertEquals(2, rendering.variableRanges.size)
    }

    @Test
    fun sectionRendersAsValidTemplateTextWhenTheValueIsLeftAsAVariable() {
        // What WtTemplateWrapExecutor feeds to TemplateManager: the tag's own
        // placeholder survives as $NAME$ so the template mirrors it.
        val rendering = WtWrapRenderer.render(WtWrapTag.SECTION, "\$SELECTION$", variableValue = WtWrapTag.VARIABLE)
        assertEquals(
            "<section begin=\"\$NAME$\" />\n\$SELECTION$\n<section end=\"\$NAME$\" />",
            rendering.text,
        )
    }

    // ---- indent detection -----------------------------------------------

    @Test
    fun indentOfLineAtReadsLeadingWhitespaceOfTheCaretsLine() {
        val text = "no indent\n    spaced\n\ttabbed"
        assertEquals("", WtWrapRenderer.indentOfLineAt(text, 3))
        assertEquals("    ", WtWrapRenderer.indentOfLineAt(text, text.indexOf("spaced")))
        assertEquals("\t", WtWrapRenderer.indentOfLineAt(text, text.indexOf("tabbed")))
    }

    @Test
    fun indentOfLineAtToleratesOutOfRangeOffsets() {
        assertEquals("", WtWrapRenderer.indentOfLineAt("", 0))
        assertEquals("", WtWrapRenderer.indentOfLineAt("abc", 99))
    }
}
