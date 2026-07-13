package org.limepepper.lang.wikitext.annotation

import java.awt.geom.Point2D

/**
 * Pure geometry for bounding-box interactions — hit-testing and the
 * move/resize/draw math — with no Swing or IntelliJ dependencies, so the
 * whole drag state machine is unit-testable without a UI.
 *
 * All coordinates are image pixels; the canvas converts to/from screen
 * space (zoom) before calling in. Tolerances are therefore also in image
 * pixels: callers divide their on-screen tolerance by the zoom factor.
 */
object BoxGeometry {
    /** The eight resize handles; [dx]/[dy] are -1/0/+1 edge selectors. */
    enum class Handle(val dx: Int, val dy: Int) {
        NW(-1, -1), N(0, -1), NE(1, -1),
        W(-1, 0), E(1, 0),
        SW(-1, 1), S(0, 1), SE(1, 1),
    }

    sealed interface Hit {
        /** A resize handle of the box [boxId] (only offered on the selected box). */
        data class HandleHit(val boxId: String, val handle: Handle) : Hit

        /** The interior of box [boxId]. */
        data class BodyHit(val boxId: String) : Hit

        data object Miss : Hit
    }

    fun handleCenter(box: BoundingBox, handle: Handle): Point2D.Double =
        Point2D.Double(
            when (handle.dx) { -1 -> box.x; 1 -> box.right; else -> box.x + box.width / 2 },
            when (handle.dy) { -1 -> box.y; 1 -> box.bottom; else -> box.y + box.height / 2 },
        )

    /**
     * What is under ([px], [py])? Priority order: the selected box's handles
     * (within [handleTolerance]), then box bodies — the smallest containing
     * box wins, so a box nested inside a larger one stays reachable.
     */
    fun hitTest(
        boxes: List<BoundingBox>,
        selectedId: String?,
        px: Double,
        py: Double,
        handleTolerance: Double,
    ): Hit {
        val selected = boxes.firstOrNull { it.id == selectedId }
        if (selected != null) {
            for (handle in Handle.entries) {
                val c = handleCenter(selected, handle)
                if (px in (c.x - handleTolerance)..(c.x + handleTolerance) &&
                    py in (c.y - handleTolerance)..(c.y + handleTolerance)
                ) {
                    return Hit.HandleHit(selected.id, handle)
                }
            }
        }
        val body = boxes.filter { it.contains(px, py) }.minByOrNull { it.area }
        return if (body != null) Hit.BodyHit(body.id) else Hit.Miss
    }

    /**
     * [original] resized by dragging [handle] to ([px], [py]). Dragging an
     * edge past its opposite edge is allowed — the result is re-normalized,
     * so the box flips instead of collapsing.
     */
    fun resize(original: BoundingBox, handle: Handle, px: Double, py: Double): BoundingBox {
        var x1 = original.x
        var y1 = original.y
        var x2 = original.right
        var y2 = original.bottom
        when (handle.dx) { -1 -> x1 = px; 1 -> x2 = px }
        when (handle.dy) { -1 -> y1 = py; 1 -> y2 = py }
        return BoundingBox.fromCorners(x1, y1, x2, y2, id = original.id).copy(label = original.label)
    }

    /** [box] moved so its origin is ([px], [py]), kept fully inside the image. */
    fun moveTo(box: BoundingBox, px: Double, py: Double, imageWidth: Double, imageHeight: Double): BoundingBox =
        box.copy(
            x = px.coerceIn(0.0, (imageWidth - box.width).coerceAtLeast(0.0)),
            y = py.coerceIn(0.0, (imageHeight - box.height).coerceAtLeast(0.0)),
        )

    /** [box] clipped to the image bounds (resize can push edges outside). */
    fun clamp(box: BoundingBox, imageWidth: Double, imageHeight: Double): BoundingBox {
        val x1 = box.x.coerceIn(0.0, imageWidth)
        val y1 = box.y.coerceIn(0.0, imageHeight)
        val x2 = box.right.coerceIn(0.0, imageWidth)
        val y2 = box.bottom.coerceIn(0.0, imageHeight)
        return box.copy(x = x1, y = y1, width = x2 - x1, height = y2 - y1)
    }
}
