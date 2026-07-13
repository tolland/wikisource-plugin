package org.limepepper.lang.wikitext.annotation

import com.intellij.ui.components.JBPanel
import com.intellij.ui.components.JBScrollPane
import com.intellij.util.ui.UIUtil
import java.awt.GridBagLayout
import java.awt.image.BufferedImage
import javax.swing.JComponent

/**
 * The reusable annotation surface: an [ImageAnnotationCanvas] inside a
 * scroll pane, with the standard zoom controls. Knows nothing about where
 * the image or the boxes come from — hosts (the reference-scan pane, the
 * demo harness) load an image, hand in / observe the [model], and embed
 * [component].
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
        isWheelScrollingEnabled = false // the wheel zooms instead
    }

    val component: JComponent
        get() = scrollPane

    fun showImage(image: BufferedImage) = canvas.showImage(image)

    fun showStatus(text: String) = canvas.showStatus(text)

    fun zoomBy(factor: Double) = canvas.zoomTo(canvas.zoom * factor, canvas.visibleCenter())

    /** "Reset" fits the whole image into the pane, the same as the initial view. */
    fun resetZoom() = canvas.fitToViewport()
}
