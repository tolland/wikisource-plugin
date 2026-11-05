package org.limepepper.lang.wikitext.editor.prp

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class PageQualityEditTest {

    private val page = "<noinclude><pagequality level=\"1\" user=\"\" /></noinclude>\nBody text.<noinclude></noinclude>"

    @Test
    fun setsTheLevelAndKeepsEverythingElse() {
        assertEquals(page.replace("level=\"1\"", "level=\"3\""), PageQualityEdit.withLevel(page, 3))
    }

    @Test
    fun keepsTheUserAndHeaderText() {
        val text = "<noinclude><pagequality level=\"1\" user=\"Admin\" />{{rh|1||x|}}</noinclude>b<noinclude></noinclude>"
        assertEquals(text.replace("level=\"1\"", "level=\"3\""), PageQualityEdit.withLevel(text, 3))
    }

    @Test
    fun sameLevelIsReturnedUnchanged() {
        assertEquals(page, PageQualityEdit.withLevel(page, 1))
    }

    @Test
    fun addsATagWhenThereIsNone() {
        val text = "<noinclude></noinclude>b<noinclude></noinclude>"
        assertEquals(
            "<noinclude><pagequality level=\"3\" user=\"\" /></noinclude>b<noinclude></noinclude>",
            PageQualityEdit.withLevel(text, 3),
        )
    }

    @Test
    fun refusesWhatItCannotRoundTrip() {
        assertNull(PageQualityEdit.withLevel("", 3))
        assertNull(PageQualityEdit.withLevel("plain wikitext", 3))
    }
}
