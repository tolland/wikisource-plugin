package org.limepepper.lang.wikitext.editor.prp

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class TextRangeModelTest {

    @Test
    fun rangeClassifiesPointVsExtent() {
        assertTrue(TextRange(start = 5, end = 5).isPoint)
        assertFalse(TextRange(start = 5, end = 9).isPoint)
        assertEquals(4, TextRange(start = 5, end = 9).length)
    }

    @Test
    fun rejectsInvertedOrNegativeRange() {
        assertFailsWith<IllegalArgumentException> { TextRange(start = 9, end = 5) }
        assertFailsWith<IllegalArgumentException> { TextRange(start = -1, end = 0) }
    }

    @Test
    fun addUpdateRemoveFireListenerAndTrackState() {
        val model = TextRangeModel()
        var changes = 0
        model.addListener(object : TextRangeModel.Listener {
            override fun rangesChanged() { changes++ }
        })
        val range = TextRange(id = "r1", start = 2, end = 6)
        model.add(range)
        assertEquals(listOf(range), model.ranges())

        model.update(range.copy(end = 10))
        assertEquals(10, model["r1"]!!.end)

        model.remove("r1")
        assertNull(model["r1"])
        assertEquals(3, changes)
    }

    @Test
    fun setAllReplacesAndClearsDanglingSelection() {
        val model = TextRangeModel()
        model.add(TextRange(id = "a", start = 0, end = 1))
        model.select("a")
        assertEquals("a", model.selectedId)

        model.setAll(listOf(TextRange(id = "b", start = 3, end = 4)))
        assertEquals(listOf("b"), model.ranges().map { it.id })
        assertNull(model.selectedId)
    }

    @Test
    fun rejectsDuplicateIdAndUnknownUpdate() {
        val model = TextRangeModel()
        model.add(TextRange(id = "x", start = 0, end = 1))
        assertFailsWith<IllegalArgumentException> { model.add(TextRange(id = "x", start = 2, end = 3)) }
        assertFailsWith<IllegalArgumentException> { model.update(TextRange(id = "y", start = 0, end = 1)) }
    }
}
