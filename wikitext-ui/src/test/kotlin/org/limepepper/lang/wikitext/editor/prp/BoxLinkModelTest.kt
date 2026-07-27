package org.limepepper.lang.wikitext.editor.prp

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class BoxLinkModelTest {

    @Test
    fun linkUnlinkFireListenerAndTrackState() {
        val model = BoxLinkModel()
        var changes = 0
        model.addListener(object : BoxLinkModel.Listener {
            override fun linksChanged() { changes++ }
        })
        model.link("b1", "r1")
        assertEquals("r1", model.rangeFor("b1"))
        assertTrue(model.isLinked("b1"))
        assertEquals(1, changes)

        // Re-linking to the same range is a no-op.
        model.link("b1", "r1")
        assertEquals(1, changes)

        // Re-linking to another range repoints the box's single link.
        model.link("b1", "r2")
        assertEquals("r2", model.rangeFor("b1"))
        assertEquals(2, changes)

        model.unlink("b1")
        assertNull(model.rangeFor("b1"))
        assertFalse(model.isLinked("b1"))
        assertEquals(3, changes)

        // Unlinking an unknown box is a no-op.
        model.unlink("b1")
        assertEquals(3, changes)
    }

    @Test
    fun severalBoxesMayTargetOneRange() {
        val model = BoxLinkModel()
        model.link("b1", "r1")
        model.link("b2", "r1")
        model.link("b3", "r2")
        assertEquals(listOf("b1", "b2"), model.boxesFor("r1"))
    }

    @Test
    fun retainRangesDropsLinksToDeletedOrReplacedRanges() {
        val model = BoxLinkModel()
        model.link("b1", "r1")
        model.link("b2", "r2")
        var changes = 0
        model.addListener(object : BoxLinkModel.Listener {
            override fun linksChanged() { changes++ }
        })
        model.retainRanges(setOf("r1", "r2"))
        assertEquals(0, changes) // nothing invalid, no event

        model.retainRanges(setOf("r1"))
        assertEquals(mapOf("b1" to "r1"), model.links())
        assertEquals(1, changes)
    }

    @Test
    fun retainBoxesDropsLinksOfDeletedBoxes() {
        val model = BoxLinkModel()
        model.link("b1", "r1")
        model.link("b2", "r1")
        model.retainBoxes(setOf("b2"))
        assertEquals(mapOf("b2" to "r1"), model.links())
    }

    @Test
    fun setAllReplacesWholesale() {
        val model = BoxLinkModel()
        model.link("b1", "r1")
        model.setAll(mapOf("b9" to "r9"))
        assertNull(model.rangeFor("b1"))
        assertEquals("r9", model.rangeFor("b9"))
    }
}
