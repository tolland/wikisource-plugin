package org.limepepper.lang.wikitext.preview

import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.*
import com.intellij.openapi.diagnostic.logger
import com.intellij.ui.JBColor
import com.intellij.util.ui.JBUI
import javax.swing.JComponent

private val TOOLBAR_LOG = logger<WtPreviewToolbar>()

/**
 * Inset toolbar running along the top of the preview pane (replacing the
 * hover/floating buttons). One toolbar, two button sets, switched by
 * [WtRenderPreviewBrowser.showReferenceImage] via per-action `update()`
 * visibility:
 *
 *  - rendered preview: mode toggle, reload
 *  - reference image:  mode toggle, zoom in/out, reset zoom, send-to-OCR (stub)
 */
internal class WtPreviewToolbar(
    private val previewBrowser: WtRenderPreviewBrowser,
) {
    val component: JComponent

    init {
        val group = DefaultActionGroup(
            ToggleReferenceImageAction(previewBrowser),
            ReloadPreviewAction(previewBrowser),
            ZoomInAction(previewBrowser),
            ZoomOutAction(previewBrowser),
            ResetZoomAction(previewBrowser),
            SendToOcrAction(previewBrowser),
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
 * Proofread workflow: swap the preview pane between the rendered wikitext and
 * the reference scan the transcription is being checked against.
 */
private class ToggleReferenceImageAction(
    private val previewEditor: WtRenderPreviewBrowser,
) : ToggleAction(
    "Show Reference Image",
    "Show the page scan instead of the rendered preview",
    AllIcons.Actions.Preview,
) {
    override fun isSelected(event: AnActionEvent): Boolean = previewEditor.showReferenceImage

    override fun setSelected(event: AnActionEvent, state: Boolean) {
        previewEditor.showReferenceImage = state
    }

    override fun update(event: AnActionEvent) {
        super.update(event)
        // Only proofread-page has a scan to toggle to.
        event.presentation.isVisible = previewEditor.profile.hasReferenceImage
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

/** Base for actions that only apply to one of the two preview modes. */
private abstract class ModeAction(
    private val previewEditor: WtRenderPreviewBrowser,
    private val imageMode: Boolean,
    text: String,
    description: String,
    icon: javax.swing.Icon,
) : AnAction(text, description, icon) {
    override fun update(event: AnActionEvent) {
        event.presentation.isVisible = previewEditor.showReferenceImage == imageMode
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

private class ReloadPreviewAction(
    private val previewEditor: WtRenderPreviewBrowser,
) : ModeAction(
    previewEditor, imageMode = false,
    "Reload Preview", "Reload Wikitext preview", AllIcons.Actions.Refresh,
) {
    override fun actionPerformed(event: AnActionEvent) {
        previewEditor.reloadPreview()
    }
}

private class ZoomInAction(
    private val previewEditor: WtRenderPreviewBrowser,
) : ModeAction(
    previewEditor, imageMode = true,
    "Zoom In", "Zoom into the reference image", AllIcons.General.ZoomIn,
) {
    override fun actionPerformed(event: AnActionEvent) {
        previewEditor.zoomImage(1.25)
    }
}

private class ZoomOutAction(
    private val previewEditor: WtRenderPreviewBrowser,
) : ModeAction(
    previewEditor, imageMode = true,
    "Zoom Out", "Zoom out of the reference image", AllIcons.General.ZoomOut,
) {
    override fun actionPerformed(event: AnActionEvent) {
        previewEditor.zoomImage(1 / 1.25)
    }
}

private class ResetZoomAction(
    private val previewEditor: WtRenderPreviewBrowser,
) : ModeAction(
    previewEditor, imageMode = true,
    "Reset Zoom", "Fit the reference image to the pane", AllIcons.General.ActualZoom,
) {
    override fun actionPerformed(event: AnActionEvent) {
        previewEditor.resetImageZoom()
    }
}

private class SendToOcrAction(
    private val previewEditor: WtRenderPreviewBrowser,
) : ModeAction(
    previewEditor, imageMode = true,
    "Send to OCR", "Send the selected region of the scan to the OCR backend", AllIcons.Actions.Upload,
) {
    override fun actionPerformed(event: AnActionEvent) {
        // Stub: will POST the selected region of the scan (the whole scan if
        // nothing is selected) to the sidecar's OCR endpoint and offer the
        // recognized text to the editor.
        TOOLBAR_LOG.info("Send to OCR: not implemented yet (selection=${previewEditor.referenceSelection()})")
    }
}
