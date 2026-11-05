package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.util.registry.Registry
import org.limepepper.lang.wikitext.annotation.ImageAnnotationCanvas

/**
 * Runtime switches for the ProofreadPage preview features.
 */
object PrpPreviewFlags {

    const val PREVIEW_MODE: String = "wikitext.editing.preview.mode"
    const val PREVIEW_SPLIT_STACKED: String = "wikitext.editing.preview.splitStacked"
    const val PREVIEW_IMAGE_FIT_MODE: String = "wikitext.editing.preview.imageFitMode"
    private const val PREVIEW_IMAGE_FIT_WIDTH = "width"
    private const val PREVIEW_MODE_BOTH = "both"

    /**
     * Which preview(s) the ProofreadPage preview pane shows on open — the
     * "compare both" choice from its toolbar. Both by default: proofreading
     * means reading the scan while checking the render against it.
     *
     * Returns the id of a `PrpPreviewBrowser.Mode`; an unrecognised value
     * falls back to showing both rather than failing to open an editor.
     */
    fun previewDefaultMode(): PrpPreviewBrowser.Mode =
        when (string(PREVIEW_MODE, PREVIEW_MODE_BOTH).lowercase()) {
            "image" -> PrpPreviewBrowser.Mode.IMAGE_ONLY
            "render" -> PrpPreviewBrowser.Mode.RENDER_ONLY
            else -> PrpPreviewBrowser.Mode.SPLIT
        }

    /**
     * Whether the two previews are tiled stacked (scan above render) rather
     * than side by side, when both are shown.
     *
     * Note these are *defaults*, not persisted preferences — nothing stores
     * the pane's mode or orientation across sessions, so they apply on every
     * open and a toolbar change lasts only for that editor's lifetime.
     */
    fun previewSplitStacked(): Boolean = boolean(PREVIEW_SPLIT_STACKED, true)

    /**
     * The reference scan's default zoom fit. Width by default: the scan pane
     * is usually shorter than it is wide now that [previewSplitStacked]
     * stacks it above the render, and fitting to the whole page there leaves
     * the scan small with unused space on each side. Fitting to width uses
     * the space actually available, at the cost of scrolling down the page —
     * which is how a reader treats a real book anyway.
     *
     * Returns an `ImageAnnotationCanvas.FitMode` id; an unrecognised value
     * falls back to width rather than failing to open an editor.
     */
    fun previewImageFitMode(): ImageAnnotationCanvas.FitMode =
        when (string(PREVIEW_IMAGE_FIT_MODE, PREVIEW_IMAGE_FIT_WIDTH).lowercase()) {
            "page" -> ImageAnnotationCanvas.FitMode.PAGE
            else -> ImageAnnotationCanvas.FitMode.WIDTH
        }

    private fun boolean(key: String, default: Boolean): Boolean =
        runCatching { Registry.`is`(key, default) }
            .onFailure { thisLogger().debug("registry key $key unavailable, using $default", it) }
            .getOrDefault(default)

    private fun string(key: String, default: String): String =
        runCatching { Registry.stringValue(key) }
            .onFailure { thisLogger().debug("registry key $key unavailable, using $default", it) }
            .getOrDefault(default)
            .ifBlank { default }
}
