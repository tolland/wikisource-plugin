package org.limepepper.lang.wikitext.annotation

import com.intellij.ui.JBColor
import org.limepepper.lang.wikitext.annotation.AnnotationPalette.withAlpha
import java.awt.Color
import java.awt.Cursor
import java.awt.Dimension
import java.awt.Graphics
import java.awt.Graphics2D
import java.awt.Point
import java.awt.Rectangle
import java.awt.RenderingHints
import java.awt.event.KeyAdapter
import java.awt.event.KeyEvent
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import java.awt.geom.AffineTransform
import java.awt.geom.Point2D
import java.awt.image.BufferedImage
import javax.swing.JComponent
import javax.swing.JPopupMenu
import javax.swing.JScrollPane
import javax.swing.SwingUtilities
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt

/**
 * Zoomable image canvas with editable bounding-box annotations — the
 * reusable drawing surface behind the reference-scan pane. Owns rendering
 * (image, boxes, handles) and the mouse/keyboard interactions; the boxes
 * themselves live in the shared [model].
 *
 * Interactions:
 *  - left-drag on empty image: draw a new box
 *  - left-click on a box: select it; left-drag inside it: move it
 *  - left-drag a handle of the selected box: resize (crossing over flips)
 *  - Delete/Backspace: delete the selected box; Escape: cancel the drag in
 *    progress (restoring the original geometry) or clear the selection
 *  - middle-drag: pan
 *  - dragging a box gesture past the viewport edge auto-pans toward the
 *    cursor until the image extent (or the cursor returns inside)
 *
 * The wheel is deliberately not handled here: the canvas has no wheel
 * listener, so AWT retargets wheel events to the enclosing
 * [ImageAnnotationPane], which owns the conventional scroll/zoom scheme
 * (wheel scrolls, Shift-wheel scrolls horizontally, Ctrl-wheel zooms via
 * [wheelZoom]).
 *
 * The canvas reports its size as image-size x zoom, so it must live inside
 * a scroll pane, supplied via [scrollPaneProvider] (a provider because the
 * scroll pane is constructed around the canvas).
 */
class ImageAnnotationCanvas(
    val model: BoundingBoxModel,
    private val scrollPaneProvider: () -> JScrollPane,
) : JComponent() {
    private var image: BufferedImage? = null
    private var statusText: String? = null

    var zoom: Double = 1.0
        private set

    /**
     * Host hook for the right-click menu: called with the box under the
     * cursor (already selected) or null on empty space; a null return shows
     * no menu. The canvas stays ignorant of what the actions mean.
     */
    var popupMenuFactory: ((BoundingBox?) -> JPopupMenu?)? = null

    /** The drag in progress, if any. All coordinates are image pixels. */
    private sealed interface Gesture {
        /** Rubber-banding a new box; becomes a model box on release. */
        class DrawNew(val startX: Double, val startY: Double) : Gesture {
            var currentX: Double = startX
            var currentY: Double = startY

            fun box(): BoundingBox = BoundingBox.fromCorners(startX, startY, currentX, currentY)
        }

        /** Dragging the body of [original]; grab* is the cursor offset from its origin. */
        class Move(val original: BoundingBox, val grabDx: Double, val grabDy: Double) : Gesture

        class Resize(val original: BoundingBox, val handle: BoxGeometry.Handle) : Gesture
    }

    private var gesture: Gesture? = null

    // Middle-button pan state, in screen coordinates so the math is
    // unaffected by the canvas itself moving under the cursor mid-drag.
    private var panScreenOrigin: Point? = null
    private var panViewOrigin: Point? = null

    init {
        isFocusable = true
        val mouse = object : MouseAdapter() {
            override fun mousePressed(e: MouseEvent) {
                requestFocusInWindow()
                if (e.isPopupTrigger) {
                    showPopup(e)
                } else if (SwingUtilities.isMiddleMouseButton(e)) {
                    panScreenOrigin = e.locationOnScreen
                    panViewOrigin = scrollPaneProvider().viewport.viewPosition
                    cursor = Cursor.getPredefinedCursor(Cursor.MOVE_CURSOR)
                } else if (SwingUtilities.isLeftMouseButton(e) && image != null) {
                    startGesture(toImagePoint(e.point))
                }
            }

            override fun mouseDragged(e: MouseEvent) {
                val screenOrigin = panScreenOrigin
                val viewOrigin = panViewOrigin
                if (screenOrigin != null && viewOrigin != null) {
                    val onScreen = e.locationOnScreen
                    scrollPaneProvider().viewport.viewPosition = clampViewPosition(Point(
                        viewOrigin.x - (onScreen.x - screenOrigin.x),
                        viewOrigin.y - (onScreen.y - screenOrigin.y),
                    ))
                } else if (gesture != null) {
                    // Keep the drag point visible: pans toward a cursor held
                    // past the viewport edge (the autoscrolls timer re-fires
                    // this handler while it stays outside), a no-op while the
                    // cursor is inside. The viewport clamps at the extents.
                    scrollRectToVisible(Rectangle(e.x, e.y, 1, 1))
                    dragGesture(toImagePoint(e.point))
                }
            }

            override fun mouseReleased(e: MouseEvent) {
                if (e.isPopupTrigger) {
                    showPopup(e)
                } else if (SwingUtilities.isMiddleMouseButton(e)) {
                    panScreenOrigin = null
                    panViewOrigin = null
                    updateCursor(e.point)
                } else if (SwingUtilities.isLeftMouseButton(e)) {
                    finishGesture()
                    updateCursor(e.point)
                }
            }

            override fun mouseMoved(e: MouseEvent) {
                updateCursor(e.point)
            }
        }
        addMouseListener(mouse)
        addMouseMotionListener(mouse)

        addKeyListener(object : KeyAdapter() {
            override fun keyPressed(e: KeyEvent) {
                when (e.keyCode) {
                    KeyEvent.VK_DELETE, KeyEvent.VK_BACK_SPACE ->
                        model.selectedId?.let(model::remove)
                    KeyEvent.VK_ESCAPE -> cancelGesture()
                }
            }
        })

        model.addListener(object : BoundingBoxModel.Listener {
            override fun boxesChanged() = repaint()

            override fun selectionChanged() = repaint()
        })
    }

    // ---- gestures -------------------------------------------------------

    private fun startGesture(p: Point2D.Double) {
        when (val hit = BoxGeometry.hitTest(
            model.boxes(), model.selectedId, p.x, p.y, HANDLE_HIT_RADIUS_PX / zoom,
        )) {
            is BoxGeometry.Hit.HandleHit -> {
                gesture = Gesture.Resize(model[hit.boxId]!!, hit.handle)
            }
            is BoxGeometry.Hit.BodyHit -> {
                val box = model[hit.boxId]!!
                model.select(box.id)
                gesture = Gesture.Move(box, p.x - box.x, p.y - box.y)
            }
            BoxGeometry.Hit.Miss -> {
                model.select(null)
                gesture = Gesture.DrawNew(p.x, p.y)
            }
        }
        // Swing's drag autoscroll: while the button is held outside the
        // viewport, synthesized drag events keep coming and the view pans
        // toward the cursor (clamped at the image extent) until the cursor
        // comes back inside. Enabled only for the duration of a box gesture
        // so it never fights the middle-button pan, which drives
        // viewPosition itself.
        autoscrolls = true
        repaint()
    }

    private fun dragGesture(p: Point2D.Double) {
        val img = image ?: return
        when (val g = gesture) {
            is Gesture.DrawNew -> {
                g.currentX = p.x
                g.currentY = p.y
                repaint()
            }
            is Gesture.Move -> model.update(BoxGeometry.moveTo(
                g.original, p.x - g.grabDx, p.y - g.grabDy,
                img.width.toDouble(), img.height.toDouble(),
            ))
            is Gesture.Resize -> model.update(BoxGeometry.clamp(
                BoxGeometry.resize(g.original, g.handle, p.x, p.y),
                img.width.toDouble(), img.height.toDouble(),
            ))
            null -> {}
        }
    }

    private fun finishGesture() {
        val g = gesture
        gesture = null
        autoscrolls = false
        if (g is Gesture.DrawNew) {
            val box = g.box()
            // A degenerate drag is a click on empty space: selection was
            // already cleared on press, nothing to add.
            if (box.width >= MIN_BOX_PX && box.height >= MIN_BOX_PX) {
                model.add(box)
                model.select(box.id)
            }
        }
        repaint()
    }

    /** Escape: abandon the drag, restoring pre-drag geometry, else deselect. */
    private fun cancelGesture() {
        when (val g = gesture) {
            is Gesture.Move -> model.update(g.original)
            is Gesture.Resize -> model.update(g.original)
            is Gesture.DrawNew -> {}
            null -> model.select(null)
        }
        gesture = null
        // setAutoscrolls(false) also stops the synthesized-drag timer, so an
        // Escape mid-drag stops the panning immediately.
        autoscrolls = false
        repaint()
    }

    /** Selects the box under a popup click, then delegates to the host menu. */
    private fun showPopup(e: MouseEvent) {
        if (image == null) {
            return
        }
        val p = toImagePoint(e.point)
        val box = when (val hit = BoxGeometry.hitTest(model.boxes(), model.selectedId, p.x, p.y, HANDLE_HIT_RADIUS_PX / zoom)) {
            is BoxGeometry.Hit.HandleHit -> model[hit.boxId]
            is BoxGeometry.Hit.BodyHit -> model[hit.boxId]
            BoxGeometry.Hit.Miss -> null
        }
        box?.let { model.select(it.id) }
        popupMenuFactory?.invoke(box)?.show(this, e.x, e.y)
    }

    /** Selects [boxId] and scrolls it into view (e.g. from a gutter click). */
    fun revealBox(boxId: String) {
        val box = model[boxId] ?: return
        model.select(boxId)
        val margin = 40
        scrollRectToVisible(Rectangle(
            (box.x * zoom).roundToInt() - margin,
            (box.y * zoom).roundToInt() - margin,
            (box.width * zoom).roundToInt() + 2 * margin,
            (box.height * zoom).roundToInt() + 2 * margin,
        ))
        repaint()
    }

    // ---- image / zoom ---------------------------------------------------

    fun showImage(loaded: BufferedImage) {
        image = loaded
        statusText = null
        updateCursor(null)
        fitToViewport()
    }

    fun showStatus(text: String) {
        statusText = text
        revalidate()
        repaint()
    }

    /**
     * Rescales so [anchor] (a point on the canvas, e.g. the cursor) stays
     * put on screen: remember which image pixel and viewport position the
     * anchor is at, resize, then scroll that pixel back under it.
     */
    /**
     * Ctrl-wheel zoom entry point for the pane's wheel handler; ignored
     * mid-gesture so the scale never shifts under a drag in progress.
     */
    fun wheelZoom(rotation: Double, anchor: Point) {
        if (image != null && gesture == null) {
            zoomTo(zoom * WHEEL_ZOOM_STEP.pow(-rotation), anchor)
        }
    }

    fun zoomTo(newZoom: Double, anchor: Point) {
        if (image == null) {
            return
        }
        val clamped = newZoom.coerceIn(MIN_ZOOM, MAX_ZOOM)
        if (clamped == zoom) {
            return
        }
        val imageX = anchor.x / zoom
        val imageY = anchor.y / zoom
        val scrollPane = scrollPaneProvider()
        val viewport = scrollPane.viewport
        val anchorInViewport = SwingUtilities.convertPoint(this, anchor, viewport)

        zoom = clamped
        revalidate()
        scrollPane.validate() // lay out now so the new canvas position is known

        val canvasInView = SwingUtilities.convertPoint(this, Point(0, 0), viewport.view)
        viewport.viewPosition = clampViewPosition(Point(
            (imageX * zoom + canvasInView.x - anchorInViewport.x).roundToInt(),
            (imageY * zoom + canvasInView.y - anchorInViewport.y).roundToInt(),
        ))
        repaint()
    }

    fun fitToViewport() {
        val img = image ?: return
        val extent = scrollPaneProvider().viewport.extentSize
        zoom = if (extent.width > 0 && extent.height > 0) {
            min(
                extent.width.toDouble() / img.width,
                extent.height.toDouble() / img.height,
            ).coerceIn(MIN_ZOOM, MAX_ZOOM)
        } else {
            1.0
        }
        revalidate()
        repaint()
    }

    fun visibleCenter(): Point {
        val rect = visibleRect
        return Point(rect.x + rect.width / 2, rect.y + rect.height / 2)
    }

    // ---- helpers ---------------------------------------------------------

    private fun updateCursor(canvasPoint: Point?) {
        val img = image
        if (img == null) {
            cursor = Cursor.getDefaultCursor()
            return
        }
        val hit = canvasPoint?.let {
            val p = toImagePoint(it)
            BoxGeometry.hitTest(model.boxes(), model.selectedId, p.x, p.y, HANDLE_HIT_RADIUS_PX / zoom)
        }
        cursor = when (hit) {
            is BoxGeometry.Hit.HandleHit -> Cursor.getPredefinedCursor(RESIZE_CURSORS.getValue(hit.handle))
            is BoxGeometry.Hit.BodyHit -> Cursor.getPredefinedCursor(Cursor.MOVE_CURSOR)
            else -> Cursor.getPredefinedCursor(Cursor.CROSSHAIR_CURSOR)
        }
    }

    private fun toImagePoint(canvasPoint: Point): Point2D.Double {
        val img = image ?: return Point2D.Double(0.0, 0.0)
        return Point2D.Double(
            (canvasPoint.x / zoom).coerceIn(0.0, img.width.toDouble()),
            (canvasPoint.y / zoom).coerceIn(0.0, img.height.toDouble()),
        )
    }

    private fun clampViewPosition(position: Point): Point {
        val viewport = scrollPaneProvider().viewport
        val viewSize = viewport.viewSize
        val extent = viewport.extentSize
        return Point(
            position.x.coerceIn(0, max(0, viewSize.width - extent.width)),
            position.y.coerceIn(0, max(0, viewSize.height - extent.height)),
        )
    }

    override fun getPreferredSize(): Dimension {
        val img = image ?: return Dimension(400, 300)
        return Dimension(
            (img.width * zoom).roundToInt(),
            (img.height * zoom).roundToInt(),
        )
    }

    // ---- painting --------------------------------------------------------

    override fun paintComponent(g: Graphics) {
        val g2 = g as Graphics2D
        val img = image
        if (img == null) {
            statusText?.let { text ->
                g2.color = JBColor.foreground()
                val metrics = g2.fontMetrics
                g2.drawString(
                    text,
                    (width - metrics.stringWidth(text)) / 2,
                    (height + metrics.ascent) / 2,
                )
            }
            return
        }
        g2.setRenderingHint(
            RenderingHints.KEY_INTERPOLATION,
            RenderingHints.VALUE_INTERPOLATION_BILINEAR,
        )
        g2.drawImage(img, AffineTransform.getScaleInstance(zoom, zoom), null)

        g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
        val boxes = model.boxes()
        for ((index, box) in boxes.withIndex()) {
            paintBox(g2, box, AnnotationPalette.colorFor(index), selected = box.id == model.selectedId)
        }
        (gesture as? Gesture.DrawNew)?.let { draw ->
            paintBox(g2, draw.box(), AnnotationPalette.colorFor(boxes.size), selected = false)
        }
    }

    private fun paintBox(g2: Graphics2D, box: BoundingBox, color: Color, selected: Boolean) {
        val x = (box.x * zoom).roundToInt()
        val y = (box.y * zoom).roundToInt()
        val w = (box.width * zoom).roundToInt()
        val h = (box.height * zoom).roundToInt()

        g2.color = color.withAlpha(if (selected) 60 else 30)
        g2.fillRect(x, y, w, h)
        g2.color = color
        g2.drawRect(x, y, w, h)

        box.label?.let { label ->
            val metrics = g2.fontMetrics
            g2.drawString(label, x, max(metrics.ascent, y - metrics.descent - 1))
        }

        // A filled corner dot marks a box linked to a text range.
        if (box.linked) {
            g2.fillOval(x + 3, y + 3, LINK_DOT_PX, LINK_DOT_PX)
        }

        if (selected) {
            for (handle in BoxGeometry.Handle.entries) {
                val c = BoxGeometry.handleCenter(box, handle)
                val hx = (c.x * zoom).roundToInt() - HANDLE_SIZE_PX / 2
                val hy = (c.y * zoom).roundToInt() - HANDLE_SIZE_PX / 2
                g2.color = HANDLE_FILL
                g2.fillRect(hx, hy, HANDLE_SIZE_PX, HANDLE_SIZE_PX)
                g2.color = color
                g2.drawRect(hx, hy, HANDLE_SIZE_PX, HANDLE_SIZE_PX)
            }
        }
    }

    private companion object {
        const val MIN_ZOOM = 0.1
        const val MAX_ZOOM = 16.0

        /** Zoom multiplier per wheel notch. */
        const val WHEEL_ZOOM_STEP = 1.15

        /** Drags smaller than this (in image pixels) count as a plain click. */
        const val MIN_BOX_PX = 3.0

        /** Handle grab tolerance and drawn size, in screen pixels. */
        const val HANDLE_HIT_RADIUS_PX = 6.0
        const val HANDLE_SIZE_PX = 7

        val RESIZE_CURSORS = mapOf(
            BoxGeometry.Handle.NW to Cursor.NW_RESIZE_CURSOR,
            BoxGeometry.Handle.N to Cursor.N_RESIZE_CURSOR,
            BoxGeometry.Handle.NE to Cursor.NE_RESIZE_CURSOR,
            BoxGeometry.Handle.W to Cursor.W_RESIZE_CURSOR,
            BoxGeometry.Handle.E to Cursor.E_RESIZE_CURSOR,
            BoxGeometry.Handle.SW to Cursor.SW_RESIZE_CURSOR,
            BoxGeometry.Handle.S to Cursor.S_RESIZE_CURSOR,
            BoxGeometry.Handle.SE to Cursor.SE_RESIZE_CURSOR,
        )

        /** Diameter of the linked-box corner dot, in screen pixels. */
        const val LINK_DOT_PX = 8

        val HANDLE_FILL = JBColor(Color.WHITE, Color(0x3C3F41))
    }
}
