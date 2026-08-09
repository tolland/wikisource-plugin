package org.limepepper.lang.wikitext.annotation

import com.intellij.ui.components.JBPanel
import com.intellij.ui.components.JBScrollPane
import com.intellij.util.ui.UIUtil
import java.awt.GridBagLayout
import java.awt.event.MouseWheelEvent
import java.awt.image.BufferedImage
import javax.swing.JComponent
import javax.swing.SwingUtilities
import kotlin.math.roundToInt

/**
 * The reusable annotation surface: an [ImageAnnotationCanvas] inside a
 * scroll pane, with the standard zoom controls. Knows nothing about where
 * the image or the boxes come from — hosts (the reference-scan pane, the
 * demo harness) load an image, hand in / observe the [model], and embed
 * [component].
 *
 * The pane owns all wheel handling (see [handleWheel]) — the conventional
 * scroll/zoom scheme for the whole surface — while the canvas keeps the
 * click/drag interactions for the boxes themselves.
 */
class ImageAnnotationPane(
    val model: BoundingBoxModel = BoundingBoxModel(),
) {
    val canvas: ImageAnnotationCanvas = ImageAnnotationCanvas(model) { scrollPane }

    // GridBagLayout centers the canvas when it is smaller than the viewport.
    private val scrollPane: JBScrollPane = JBScrollPane(
        JBPanel<JBPanel<*>>(GridBagLayout()).apply {
            background = UIUtil.getPanelBackground()
            add(canvas)
        },
    ).apply {
        border = null
        // handleWheel is the single wheel consumer: the canvas has no wheel
        // listener, so AWT retargets its wheel events up to this scroll pane,
        // and the stock scrolling would double up with the listener below.
        isWheelScrollingEnabled = false
        addMouseWheelListener(::handleWheel)
    }

    val component: JComponent
        get() = scrollPane

    /**
     * Conventional wheel scheme: plain wheel scrolls vertically, Shift-wheel
     * horizontally, Ctrl-wheel (Cmd-wheel on mac) zooms about the cursor.
     */
    private fun handleWheel(e: MouseWheelEvent) {
        e.consume()
        if (e.isControlDown || e.isMetaDown) {
            canvas.wheelZoom(
                e.preciseWheelRotation,
                SwingUtilities.convertPoint(e.component, e.point, canvas),
            )
        } else {
            val bar = if (e.isShiftDown) scrollPane.horizontalScrollBar else scrollPane.verticalScrollBar
            bar.value += (e.preciseWheelRotation * WHEEL_SCROLL_STEP_PX).roundToInt()
        }
    }

    /** Which fit [showImage] and [resetZoom] use. See [ImageAnnotationCanvas.FitMode]. */
    var defaultFitMode: ImageAnnotationCanvas.FitMode
        get() = canvas.defaultFitMode
        set(value) { canvas.defaultFitMode = value }

    fun showImage(image: BufferedImage) = canvas.showImage(image)

    fun showStatus(text: String) = canvas.showStatus(text)

    fun zoomBy(factor: Double) = canvas.zoomTo(canvas.zoom * factor, canvas.visibleCenter())

    /** "Reset" returns to [defaultFitMode], the same fit the initial view used. */
    fun resetZoom() = canvas.fitToDefault()

    /** Always fits the whole page, regardless of [defaultFitMode]. */
    fun fitToPage() = canvas.fitToViewport()

    /** Always fits the page's width, regardless of [defaultFitMode]. */
    fun fitToWidth() = canvas.fitToWidth()

    /** Selects [boxId] and scrolls it into view. */
    fun revealBox(boxId: String) = canvas.revealBox(boxId)

    private companion object {
        /** Scroll distance per wheel notch, in screen pixels. */
        const val WHEEL_SCROLL_STEP_PX = 60
    }
}
