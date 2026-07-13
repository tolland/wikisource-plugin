package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.vfs.VirtualFile
import org.limepepper.lang.wikitext.annotation.BoundingBox
import org.limepepper.lang.wikitext.annotation.BoundingBoxModel
import org.limepepper.lang.wikitext.annotation.ImageAnnotationPane
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.awt.Rectangle
import java.awt.image.BufferedImage
import java.io.ByteArrayInputStream
import java.io.IOException
import java.net.URI
import java.util.Base64
import javax.imageio.ImageIO
import javax.swing.JComponent
import kotlin.math.roundToInt

private val IMAGE_LOG = logger<WtReferenceImagePane>()

/**
 * The reference-scan half of the proofread preview, drawn on a plain Swing
 * canvas rather than a browser: proofreading needs to zoom well past 100%,
 * and the OCR workflow needs the decoded pixels anyway to crop a selected
 * region — neither of which a JCEF page gives us cleanly.
 *
 * The scan is independent of the document text, so it is fetched and decoded
 * once — lazily, on first show — and the canvas (zoom, scroll, boxes) stays
 * alive across mode toggles.
 *
 * The drawing surface is the reusable [ImageAnnotationPane]: bounding boxes
 * drawn over the scan (left-drag draws, drag moves, handles resize,
 * Delete removes, wheel zooms, middle-drag pans). For wikisource:// pages
 * the boxes persist: they load from the sidecar with the image and every
 * change is written behind via [WtAnnotationSync] to the per-page SVG
 * annotation document. For non-VFS files the canvas still works, just
 * in-memory.
 */
class WtReferenceImagePane(
    private val file: VirtualFile,
) : Disposable {
    private val annotationPane = ImageAnnotationPane()

    val component: JComponent
        get() = annotationPane.component

    /** The shared box set — the editor-side anchor chrome observes this. */
    val model: BoundingBoxModel
        get() = annotationPane.model

    /** Revision the file's cached content is based on, for new anchors. */
    val baseRevid: Long?
        get() = (file as? WtVirtualFile)?.revid

    /** Hands the right-click menu over to the host (see [ImageAnnotationCanvas.popupMenuFactory]). */
    fun installPopupMenu(factory: (BoundingBox?) -> javax.swing.JPopupMenu?) {
        annotationPane.canvas.popupMenuFactory = factory
    }

    /** Selects [boxId] and scrolls the canvas to it (gutter-icon click path). */
    fun revealBox(boxId: String) = annotationPane.revealBox(boxId)

    @Volatile
    private var disposed = false

    private var loadStarted = false

    /**
     * The selected box in image pixel coordinates, if any — the region the
     * OCR actions crop and send.
     */
    val selection: Rectangle?
        get() = annotationPane.model.selected?.let { box ->
            Rectangle(
                box.x.roundToInt(),
                box.y.roundToInt(),
                box.width.roundToInt(),
                box.height.roundToInt(),
            )
        }

    /** Fetches and decodes the scan on first call; later calls are no-ops. */
    fun ensureLoaded() {
        if (loadStarted) {
            return
        }
        loadStarted = true
        annotationPane.showStatus("Loading reference image…")
        val vfsPath = (file as? WtVirtualFile)?.path
        ApplicationManager.getApplication().executeOnPooledThread {
            var failure: String? = null
            val backend = WtVfsService.instance.backend
            val image = try {
                loadImage(backend.pageImageUrl(
                    vfsPath,
                    if (file is WtVirtualFile) null else file.nameWithoutExtension,
                ))
            } catch (e: Exception) {
                IMAGE_LOG.warn("reference image load failed for ${file.path}", e)
                failure = e.message ?: e.javaClass.simpleName
                null
            }
            // Boxes ride along with the scan; a failure here degrades to a
            // bare image rather than blocking it.
            val annotations = if (image != null && vfsPath != null) {
                try {
                    backend.listAnnotations(vfsPath)
                } catch (e: Exception) {
                    IMAGE_LOG.warn("annotation load failed for $vfsPath", e)
                    null
                }
            } else {
                null
            }
            ApplicationManager.getApplication().invokeLater {
                if (disposed) {
                    return@invokeLater
                }
                if (image == null) {
                    annotationPane.showStatus("Could not load the reference image: $failure")
                    return@invokeLater
                }
                annotationPane.showImage(image)
                if (annotations != null && vfsPath != null) {
                    annotationPane.model.setAll(
                        annotations.annotations
                            .filter { it.shape == "rect" } // others are view-only, drawn out-of-band
                            .map {
                                BoundingBox(
                                    id = it.id,
                                    x = it.x,
                                    y = it.y,
                                    width = it.width,
                                    height = it.height,
                                    label = it.label,
                                    textStart = it.textStart,
                                    textEnd = it.textEnd,
                                    anchorRevid = it.anchorRevid,
                                )
                            },
                    )
                    val sync = WtAnnotationSync(
                        annotationPane.model,
                        vfsPath,
                        image.width,
                        image.height,
                    )
                    Disposer.register(this, sync)
                    sync.seed(annotations.annotations)
                }
            }
        }
    }

    fun zoomBy(factor: Double) = annotationPane.zoomBy(factor)

    /** "Reset" fits the whole scan into the pane, the same as the initial view. */
    fun resetZoom() = annotationPane.resetZoom()

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
}
