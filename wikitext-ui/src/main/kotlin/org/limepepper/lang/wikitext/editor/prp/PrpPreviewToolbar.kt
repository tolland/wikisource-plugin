package org.limepepper.lang.wikitext.editor.prp

import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.DefaultActionGroup
import com.intellij.openapi.actionSystem.ToggleAction
import com.intellij.openapi.diagnostic.logger
import com.intellij.ui.JBColor
import com.intellij.util.ui.JBUI
import javax.swing.Icon
import javax.swing.JComponent

private val TOOLBAR_LOG = logger<PrpPreviewToolbar>()

/**
 * The master toolbar that spans the whole preview side. It owns the choice of
 * *which* preview(s) are shown — the reference scan, the rendered wikitext, or
 * both tiled together — and, when both are shown, the tiling orientation.
 *
 * The per-preview controls (zoom for the scan, reload for the render) live on
 * their own toolbars inside each pane ([PrpImagePreviewToolbar],
 * [PrpRenderPreviewToolbar]) so they stay attached to their pane when the two
 * are tiled side by side.
 */
internal class PrpPreviewToolbar(
    private val previewBrowser: PrpPreviewBrowser,
) {
    val component: JComponent

    init {
        val group = DefaultActionGroup(
            ShowModeAction(
                previewBrowser, PrpPreviewBrowser.Mode.IMAGE_ONLY,
                "Reference Image", "Show only the page scan",
                AllIcons.FileTypes.Image,
            ),
            ShowModeAction(
                previewBrowser, PrpPreviewBrowser.Mode.RENDER_ONLY,
                "Rendered Preview", "Show only the rendered wikitext",
                AllIcons.Actions.Preview,
            ),
            ShowModeAction(
                previewBrowser, PrpPreviewBrowser.Mode.SPLIT,
                "Compare Both", "Tile the scan and the rendered preview together",
                AllIcons.Actions.SplitVertically,
            ),
            com.intellij.openapi.actionSystem.Separator.getInstance(),
            OrientationAction(
                previewBrowser, stacked = false,
                "Tile Side by Side", "Place the two previews left and right",
                AllIcons.Actions.SplitVertically,
            ),
            OrientationAction(
                previewBrowser, stacked = true,
                "Tile Stacked", "Place the two previews top and bottom",
                AllIcons.Actions.SplitHorizontally,
            ),
            SwapPanesAction(previewBrowser),
        )
        val toolbar = ActionManager.getInstance()
            .createActionToolbar("WikitextPreviewToolbar", group, true)
        toolbar.targetComponent = previewBrowser.component
        component = toolbar.component.apply {
            border = JBUI.Borders.customLineBottom(JBColor.border())
        }
    }
}

/**
 * A mutually exclusive choice of preview mode. Selected when the browser is in
 * that mode; selecting it switches to it.
 */
private class ShowModeAction(
    private val previewBrowser: PrpPreviewBrowser,
    private val mode: PrpPreviewBrowser.Mode,
    text: String,
    description: String,
    icon: Icon,
) : ToggleAction(text, description, icon) {
    override fun isSelected(event: AnActionEvent): Boolean = previewBrowser.mode == mode

    override fun setSelected(event: AnActionEvent, state: Boolean) {
        if (state) {
            previewBrowser.mode = mode
        }
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

/**
 * Tiling orientation for the split view. Only relevant — and only shown — when
 * both previews are visible ([PrpPreviewBrowser.Mode.SPLIT]).
 */
private class OrientationAction(
    private val previewBrowser: PrpPreviewBrowser,
    private val stacked: Boolean,
    text: String,
    description: String,
    icon: Icon,
) : ToggleAction(text, description, icon) {
    override fun isSelected(event: AnActionEvent): Boolean =
        previewBrowser.splitStacked == stacked

    override fun setSelected(event: AnActionEvent, state: Boolean) {
        if (state) {
            previewBrowser.splitStacked = stacked
        }
    }

    override fun update(event: AnActionEvent) {
        super.update(event)
        event.presentation.isEnabledAndVisible = previewBrowser.mode == PrpPreviewBrowser.Mode.SPLIT
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

/**
 * Swaps the two previews' positions in the tiled layout. Only relevant — and
 * only shown — when both previews are visible ([PrpPreviewBrowser.Mode.SPLIT]).
 */
private class SwapPanesAction(
    private val previewBrowser: PrpPreviewBrowser,
) : AnAction("Swap Panes", "Swap the positions of the two previews", AllIcons.Actions.SwapPanels) {
    override fun actionPerformed(event: AnActionEvent) {
        previewBrowser.swapped = !previewBrowser.swapped
    }

    override fun update(event: AnActionEvent) {
        event.presentation.isEnabledAndVisible = previewBrowser.mode == PrpPreviewBrowser.Mode.SPLIT
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

/**
 * The scan pane's own toolbar: zoom and OCR, which only make sense for the
 * reference image. Lives inside the image pane so it travels with it in the
 * tiled layout.
 */
internal class PrpImagePreviewToolbar(
    private val imagePane: ReferenceImagePane,
) {
    val component: JComponent

    init {
        val group = DefaultActionGroup(
            ZoomInAction(imagePane),
            ZoomOutAction(imagePane),
            ResetZoomAction(imagePane),
            SendToOcrAction(imagePane),
        )
        val toolbar = ActionManager.getInstance()
            .createActionToolbar("WikitextImagePreviewToolbar", group, true)
        toolbar.targetComponent = imagePane.component
        component = toolbar.component.apply {
            border = JBUI.Borders.customLineBottom(JBColor.border())
        }
    }
}

private class ZoomInAction(
    private val imagePane: ReferenceImagePane,
) : AnAction("Zoom In", "Zoom into the reference image", AllIcons.General.ZoomIn) {
    override fun actionPerformed(event: AnActionEvent) = imagePane.zoomBy(1.25)

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

private class ZoomOutAction(
    private val imagePane: ReferenceImagePane,
) : AnAction("Zoom Out", "Zoom out of the reference image", AllIcons.General.ZoomOut) {
    override fun actionPerformed(event: AnActionEvent) = imagePane.zoomBy(1 / 1.25)

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

private class ResetZoomAction(
    private val imagePane: ReferenceImagePane,
) : AnAction(
    "Reset Zoom",
    "Fit the reference image to the pane (see wikitext.editing.preview.imageFitMode)",
    AllIcons.General.ActualZoom,
) {
    override fun actionPerformed(event: AnActionEvent) = imagePane.resetZoom()

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

private class SendToOcrAction(
    private val imagePane: ReferenceImagePane,
) : AnAction("Send to OCR", "Send the selected region of the scan to the OCR backend", AllIcons.Actions.Upload) {
    override fun actionPerformed(event: AnActionEvent) {
        // Stub: will POST the selected region of the scan (the whole scan if
        // nothing is selected) to the sidecar's OCR endpoint and offer the
        // recognized text to the editor.
        TOOLBAR_LOG.info("Send to OCR: not implemented yet (selection=${imagePane.selection})")
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

/**
 * The render pane's own toolbar: reload and zoom, which only make sense for the
 * server-rendered preview. Lives inside the render pane so it travels with it
 * in the tiled layout. The zoom buttons drive the same zoom level as Ctrl-wheel.
 */
internal class PrpRenderPreviewToolbar(
    private val renderPane: RenderPreviewPane,
) {
    val component: JComponent

    init {
        val group = DefaultActionGroup(
            RenderReloadAction(renderPane),
            RenderZoomInAction(renderPane),
            RenderZoomOutAction(renderPane),
            RenderResetZoomAction(renderPane),
        )
        val toolbar = ActionManager.getInstance()
            .createActionToolbar("WikitextRenderPreviewToolbar", group, true)
        toolbar.targetComponent = renderPane.component
        component = toolbar.component.apply {
            border = JBUI.Borders.customLineBottom(JBColor.border())
        }
    }
}

private class RenderReloadAction(
    private val renderPane: RenderPreviewPane,
) : AnAction("Reload Preview", "Reload Wikitext preview", AllIcons.Actions.Refresh) {
    override fun actionPerformed(event: AnActionEvent) = renderPane.reload()

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

/** Base for the render-preview zoom buttons: hidden when zoom isn't supported. */
private abstract class RenderZoomAction(
    private val renderPane: RenderPreviewPane,
    text: String,
    description: String,
    icon: Icon,
) : AnAction(text, description, icon) {
    override fun update(event: AnActionEvent) {
        event.presentation.isEnabledAndVisible = renderPane.zoomSupported
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

private class RenderZoomInAction(
    private val renderPane: RenderPreviewPane,
) : RenderZoomAction(renderPane, "Zoom In", "Zoom into the rendered preview", AllIcons.General.ZoomIn) {
    override fun actionPerformed(event: AnActionEvent) = renderPane.zoomIn()
}

private class RenderZoomOutAction(
    private val renderPane: RenderPreviewPane,
) : RenderZoomAction(renderPane, "Zoom Out", "Zoom out of the rendered preview", AllIcons.General.ZoomOut) {
    override fun actionPerformed(event: AnActionEvent) = renderPane.zoomOut()
}

private class RenderResetZoomAction(
    private val renderPane: RenderPreviewPane,
) : RenderZoomAction(renderPane, "Reset Zoom", "Reset the rendered preview to 100%", AllIcons.General.ActualZoom) {
    override fun actionPerformed(event: AnActionEvent) = renderPane.resetZoom()
}
