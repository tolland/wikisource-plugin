package org.limepepper.lang.wikitext.annotation

import org.limepepper.lang.wikitext.annotation.BoxGeometry.Handle
import org.limepepper.lang.wikitext.annotation.BoxGeometry.Hit
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class BoxGeometryTest {
    private val box = BoundingBox(id = "a", x = 100.0, y = 100.0, width = 50.0, height = 40.0)

    // ---- hit testing ----------------------------------------------------

    @Test
    fun missOnEmptySpace() {
        assertEquals(Hit.Miss, BoxGeometry.hitTest(listOf(box), null, 10.0, 10.0, 5.0))
    }

    @Test
    fun bodyHitInsideBox() {
        assertEquals(Hit.BodyHit("a"), BoxGeometry.hitTest(listOf(box), null, 120.0, 120.0, 5.0))
    }

    @Test
    fun handlesOnlyOfferedOnSelectedBox() {
        // On the NW corner: a handle when "a" is selected, plain body hit when not.
        assertEquals(Hit.HandleHit("a", Handle.NW), BoxGeometry.hitTest(listOf(box), "a", 100.0, 100.0, 5.0))
        assertEquals(Hit.BodyHit("a"), BoxGeometry.hitTest(listOf(box), null, 100.0, 100.0, 5.0))
    }

    @Test
    fun handleHitWithinTolerance() {
        // SE corner is (150, 140); 4px away with 5px tolerance still grabs it.
        assertEquals(Hit.HandleHit("a", Handle.SE), BoxGeometry.hitTest(listOf(box), "a", 154.0, 144.0, 5.0))
        assertEquals(Hit.Miss, BoxGeometry.hitTest(listOf(box), "a", 156.0, 146.0, 5.0))
    }

    @Test
    fun edgeMidpointHandles() {
        // N midpoint is (125, 100), E midpoint is (150, 120).
        assertEquals(Hit.HandleHit("a", Handle.N), BoxGeometry.hitTest(listOf(box), "a", 125.0, 100.0, 5.0))
        assertEquals(Hit.HandleHit("a", Handle.E), BoxGeometry.hitTest(listOf(box), "a", 150.0, 120.0, 5.0))
    }

    @Test
    fun smallestContainingBoxWinsBodyHit() {
        val outer = BoundingBox(id = "outer", x = 0.0, y = 0.0, width = 500.0, height = 500.0)
        val inner = BoundingBox(id = "inner", x = 100.0, y = 100.0, width = 50.0, height = 50.0)
        assertEquals(Hit.BodyHit("inner"), BoxGeometry.hitTest(listOf(outer, inner), null, 120.0, 120.0, 5.0))
        assertEquals(Hit.BodyHit("outer"), BoxGeometry.hitTest(listOf(outer, inner), null, 300.0, 300.0, 5.0))
    }

    @Test
    fun selectedHandlesBeatOverlappingBody() {
        val other = BoundingBox(id = "b", x = 140.0, y = 130.0, width = 100.0, height = 100.0)
        // (150, 140) is box "a"'s SE handle and inside "b"; with "a" selected the handle wins.
        assertEquals(Hit.HandleHit("a", Handle.SE), BoxGeometry.hitTest(listOf(box, other), "a", 150.0, 140.0, 5.0))
    }

    // ---- resize ----------------------------------------------------------

    @Test
    fun resizeCornerMovesTwoEdges() {
        val resized = BoxGeometry.resize(box, Handle.SE, 200.0, 180.0)
        assertEquals(BoundingBox(id = "a", x = 100.0, y = 100.0, width = 100.0, height = 80.0), resized)
    }

    @Test
    fun resizeEdgeMovesOneAxisOnly() {
        val resized = BoxGeometry.resize(box, Handle.N, 999.0, 110.0)
        assertEquals(BoundingBox(id = "a", x = 100.0, y = 110.0, width = 50.0, height = 30.0), resized)
    }

    @Test
    fun resizeCrossingOverFlipsInsteadOfCollapsing() {
        // Drag the W edge (x=100) past the E edge (x=150) to x=170.
        val resized = BoxGeometry.resize(box, Handle.W, 170.0, 0.0)
        assertEquals(150.0, resized.x)
        assertEquals(20.0, resized.width)
        assertEquals("a", resized.id)
    }

    @Test
    fun resizeKeepsIdAndLabel() {
        val labeled = box.copy(label = "figure 1")
        val resized = BoxGeometry.resize(labeled, Handle.SE, 300.0, 300.0)
        assertEquals("a", resized.id)
        assertEquals("figure 1", resized.label)
    }

    // ---- move / clamp ----------------------------------------------------

    @Test
    fun moveClampsToImageBounds() {
        val moved = BoxGeometry.moveTo(box, -20.0, 380.0, 400.0, 400.0)
        assertEquals(0.0, moved.x)
        assertEquals(360.0, moved.y) // 400 - height 40
        assertEquals(50.0, moved.width)
    }

    @Test
    fun clampClipsOverhangingEdges() {
        val overhanging = BoundingBox(id = "c", x = -10.0, y = 380.0, width = 50.0, height = 50.0)
        val clamped = BoxGeometry.clamp(overhanging, 400.0, 400.0)
        assertEquals(BoundingBox(id = "c", x = 0.0, y = 380.0, width = 40.0, height = 20.0), clamped)
    }

    @Test
    fun fromCornersNormalizesAnyDragDirection() {
        val b = BoundingBox.fromCorners(150.0, 140.0, 100.0, 100.0)
        assertEquals(100.0, b.x)
        assertEquals(100.0, b.y)
        assertEquals(50.0, b.width)
        assertEquals(40.0, b.height)
        assertIs<String>(b.id)
    }
}
