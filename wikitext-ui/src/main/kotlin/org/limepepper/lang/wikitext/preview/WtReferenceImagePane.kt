package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.ui.JBColor
import com.intellij.ui.components.JBPanel
import com.intellij.ui.components.JBScrollPane
import com.intellij.util.ui.UIUtil
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.awt.Color
import java.awt.Cursor
import java.awt.Dimension
import java.awt.Graphics
import java.awt.Graphics2D
import java.awt.GridBagLayout
import java.awt.Point
import java.awt.Rectangle
import java.awt.RenderingHints
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import java.awt.event.MouseWheelEvent
import java.awt.geom.AffineTransform
import java.awt.image.BufferedImage
import java.io.ByteArrayInputStream
import java.io.IOException
import java.net.URI
import java.util.Base64
import javax.imageio.ImageIO
import javax.swing.JComponent
import javax.swing.SwingUtilities
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.roundToInt

private val IMAGE_LOG = logger<WtReferenceImagePane>()

/**
 * The reference-scan half of the proofread preview, drawn on a plain Swing
 * canvas rather than a browser: proofreading needs to zoom well past 100%,
 * and the OCR workflow needs the decoded pixels anyway to crop a selected
 * region — neither of which a JCEF page gives us cleanly.
 *
 * The scan is independent of the document text, so it is fetched and decoded
 * once — lazily, on first show — and the canvas (zoom, scroll, selection)
 * stays alive across mode toggles.
 *
 * Interactions on the image:
 *  - left-drag draws a selection box ([selection], in image pixels) marking
 *    the region to send to the OCR backend
 *  - scroll wheel zooms about the cursor
 *  - middle-button drag pans
 */
class WtReferenceImagePane(
    private val file: VirtualFile,
) : Disposable {
    private val canvas = ImageCanvas()

    // GridBagLayout centers the canvas when it is smaller than the viewport.
    private val scrollPane = JBScrollPane(
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

    @Volatile
    private var disposed = false

    private var loadStarted = false

    /** The drag-selected OCR region in image pixel coordinates, if any. */
    val selection: Rectangle?
        get() = canvas.selectionInImage()

    /** Fetches and decodes the scan on first call; later calls are no-ops. */
    fun ensureLoaded() {
        if (loadStarted) {
            return
        }
        loadStarted = true
        ApplicationManager.getApplication().executeOnPooledThread {
            var failure: String? = null
            val image = try {
                loadImage(WtVfsService.instance.backend.pageImageUrl(
                    (file as? WtVirtualFile)?.path,
                    if (file is WtVirtualFile) null else file.nameWithoutExtension,
                ))
            } catch (e: Exception) {
                IMAGE_LOG.warn("reference image load failed for ${file.path}", e)
                failure = e.message ?: e.javaClass.simpleName
                null
            }
            ApplicationManager.getApplication().invokeLater {
                if (!disposed) {
                    if (image != null) {
                        canvas.showImage(image)
                    } else {
                        canvas.showStatus("Could not load the reference image: $failure")
                    }
                }
            }
        }
    }

    fun zoomBy(factor: Double) {
        canvas.zoomTo(canvas.zoom * factor, canvas.visibleCenter())
    }

    /** "Reset" fits the whole scan into the pane, the same as the initial view. */
    fun resetZoom() {
        canvas.fitToViewport()
    }

    private fun loadImage(url: String): BufferedImage {
        // The fake backend hands out data: URLs; java.net can't open those.
        val decoded = if (url.startsWith("data:")) {
            val payload = url.substringAfter("base64,", missingDelimiterValue = "")
            ImageIO.read(ByteArrayInputStream(Base64.getDecoder().decode(payload)))
        } else {
            ImageIO.read(URI(url).toURL())
        }
        return decoded ?: throw IOException("unsupported image format at $url")
    }

    override fun dispose() {
        disposed = true
    }

    /**
     * The scan itself: paints the image at [zoom] scale (its preferred size,
     * so the enclosing scroll pane provides the scrollbars) plus the
     * selection overlay, and owns the mouse interactions.
     */
    private inner class ImageCanvas : JComponent() {
        private var image: BufferedImage? = null
        private var statusText: String? = "Loading reference image…"

        var zoom: Double = 1.0
            private set

        // Selection endpoints in image pixel coordinates (live during drag).
        private var selectionStart: Point? = null
        private var selectionEnd: Point? = null

        // Middle-button pan state, in screen coordinates so the math is
        // unaffected by the canvas itself moving under the cursor mid-drag.
        private var panScreenOrigin: Point? = null
        private var panViewOrigin: Point? = null

        init {
            val mouse = object : MouseAdapter() {
                override fun mousePressed(e: MouseEvent) {
                    if (SwingUtilities.isMiddleMouseButton(e)) {
                        panScreenOrigin = e.locationOnScreen
                        panViewOrigin = scrollPane.viewport.viewPosition
                        cursor = Cursor.getPredefinedCursor(Cursor.MOVE_CURSOR)
                    } else if (SwingUtilities.isLeftMouseButton(e) && image != null) {
                        selectionStart = toImagePoint(e.point)
                        selectionEnd = selectionStart
                        repaint()
                    }
                }

                override fun mouseDragged(e: MouseEvent) {
                    val screenOrigin = panScreenOrigin
                    val viewOrigin = panViewOrigin
                    if (screenOrigin != null && viewOrigin != null) {
                        val onScreen = e.locationOnScreen
                        scrollPane.viewport.viewPosition = clampViewPosition(Point(
                            viewOrigin.x - (onScreen.x - screenOrigin.x),
                            viewOrigin.y - (onScreen.y - screenOrigin.y),
                        ))
                    } else if (selectionStart != null) {
                        selectionEnd = toImagePoint(e.point)
                        repaint()
                    }
                }

                override fun mouseReleased(e: MouseEvent) {
                    if (SwingUtilities.isMiddleMouseButton(e)) {
                        panScreenOrigin = null
                        panViewOrigin = null
                        updateCursor()
                    } else if (SwingUtilities.isLeftMouseButton(e)) {
                        // A degenerate drag (a click) clears the selection.
                        if (selectionInImage() == null) {
                            selectionStart = null
                            selectionEnd = null
                        }
                        repaint()
                    }
                }

                override fun mouseWheelMoved(e: MouseWheelEvent) {
                    if (image != null) {
                        zoomTo(zoom * WHEEL_ZOOM_STEP.pow(-e.preciseWheelRotation), e.point)
                    }
                }
            }
            addMouseListener(mouse)
            addMouseMotionListener(mouse)
            addMouseWheelListener(mouse)
        }

        fun showImage(loaded: BufferedImage) {
            image = loaded
            statusText = null
            updateCursor()
            fitToViewport()
        }

        fun showStatus(text: String) {
            statusText = text
            revalidate()
            repaint()
        }

        fun selectionInImage(): Rectangle? {
            val start = selectionStart ?: return null
            val end = selectionEnd ?: return null
            val rect = Rectangle(
                min(start.x, end.x),
                min(start.y, end.y),
                abs(end.x - start.x),
                abs(end.y - start.y),
            )
            return if (rect.width >= MIN_SELECTION_PX && rect.height >= MIN_SELECTION_PX) rect else null
        }

        /**
         * Rescales so [anchor] (a point on the canvas, e.g. the cursor) stays
         * put on screen: remember which image pixel and viewport position the
         * anchor is at, resize, then scroll that pixel back under it.
         */
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
            val extent = scrollPane.viewport.extentSize
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

        private fun updateCursor() {
            cursor = if (image != null) {
                Cursor.getPredefinedCursor(Cursor.CROSSHAIR_CURSOR)
            } else {
                Cursor.getDefaultCursor()
            }
        }

        private fun toImagePoint(canvasPoint: Point): Point {
            val img = image ?: return Point(0, 0)
            return Point(
                (canvasPoint.x / zoom).roundToInt().coerceIn(0, img.width),
                (canvasPoint.y / zoom).roundToInt().coerceIn(0, img.height),
            )
        }

        private fun clampViewPosition(position: Point): Point {
            val viewport = scrollPane.viewport
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

            selectionInImage()?.let { rect ->
                val x = (rect.x * zoom).roundToInt()
                val y = (rect.y * zoom).roundToInt()
                val w = (rect.width * zoom).roundToInt()
                val h = (rect.height * zoom).roundToInt()
                g2.color = SELECTION_FILL
                g2.fillRect(x, y, w, h)
                g2.color = SELECTION_BORDER
                g2.drawRect(x, y, w, h)
            }
        }
    }

    private companion object {
        const val MIN_ZOOM = 0.1
        const val MAX_ZOOM = 16.0

        /** Zoom multiplier per wheel notch. */
        const val WHEEL_ZOOM_STEP = 1.15

        /** Drags smaller than this (in image pixels) count as a plain click. */
        const val MIN_SELECTION_PX = 3

        val SELECTION_BORDER = JBColor(Color(0x1E88E5), Color(0x64B5F6))
        val SELECTION_FILL = JBColor(Color(0x1E88E5).withAlpha(40), Color(0x64B5F6).withAlpha(40))

        fun Color.withAlpha(alpha: Int) = Color(red, green, blue, alpha)
    }
}
