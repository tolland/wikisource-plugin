package org.limepepper.lang.wikitext.annotation

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull

class BoundingBoxModelTest {
    private val model = BoundingBoxModel()
    private val box = BoundingBox(id = "a", x = 0.0, y = 0.0, width = 10.0, height = 10.0)

    private class RecordingListener : BoundingBoxModel.Listener {
        var boxEvents = 0
        var selectionEvents = 0

        override fun boxesChanged() {
            boxEvents++
        }

        override fun selectionChanged() {
            selectionEvents++
        }
    }

    @Test
    fun addUpdateRemoveRoundTrip() {
        model.add(box)
        assertEquals(listOf(box), model.boxes())

        val moved = box.copy(x = 5.0)
        model.update(moved)
        assertEquals(moved, model["a"])

        model.remove("a")
        assertEquals(emptyList(), model.boxes())
    }

    @Test
    fun addRejectsDuplicateIdAndUpdateRejectsUnknownId() {
        model.add(box)
        assertFailsWith<IllegalArgumentException> { model.add(box.copy(x = 99.0)) }
        assertFailsWith<IllegalArgumentException> { model.update(box.copy(id = "nope")) }
    }

    @Test
    fun removingSelectedBoxClearsSelection() {
        model.add(box)
        model.select("a")
        model.remove("a")
        assertNull(model.selectedId)
    }

    @Test
    fun selectionRequiresKnownBox() {
        assertFailsWith<IllegalArgumentException> { model.select("nope") }
    }

    @Test
    fun listenersSeeChangesAndOnlyRealSelectionChangesFire() {
        val listener = RecordingListener()
        model.addListener(listener)

        model.add(box)
        assertEquals(1, listener.boxEvents)

        model.select("a")
        model.select("a") // no-op, same selection
        assertEquals(1, listener.selectionEvents)

        model.removeListener(listener)
        model.remove("a")
        assertEquals(1, listener.boxEvents)
    }

    @Test
    fun setAllReplacesBoxesAndDropsStaleSelection() {
        model.add(box)
        model.select("a")

        val replacement = BoundingBox(id = "b", x = 1.0, y = 1.0, width = 2.0, height = 2.0)
        model.setAll(listOf(replacement))

        assertEquals(listOf(replacement), model.boxes())
        assertNull(model.selectedId)
    }

    @Test
    fun setAllKeepsSelectionThatSurvives() {
        model.add(box)
        model.select("a")
        model.setAll(listOf(box.copy(x = 42.0)))
        assertEquals("a", model.selectedId)
        assertEquals(42.0, model.selected?.x)
    }
}
