package org.limepepper.lang.wikitext.editor.prp

import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.*
import com.intellij.openapi.diagnostic.logger
import com.intellij.ui.JBColor
import com.intellij.util.ui.JBUI
import javax.swing.Icon
import javax.swing.JComponent

private val TOOLBAR_LOG = logger<PrpPreviewToolbar>()


internal class PrpPreviewToolbar(
    private val previewBrowser: PrpPreviewBrowser,
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
    private val previewEditor: PrpPreviewBrowser,
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
        event.presentation.isVisible = true
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

/** Base for actions that only apply to one of the two preview modes. */
private abstract class ModeAction(
    private val previewEditor: PrpPreviewBrowser,
    private val imageMode: Boolean,
    text: String,
    description: String,
    icon: Icon,
) : AnAction(text, description, icon) {
    override fun update(event: AnActionEvent) {
        event.presentation.isVisible = previewEditor.showReferenceImage == imageMode
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

private class ReloadPreviewAction(
    private val previewEditor: PrpPreviewBrowser,
) : ModeAction(
    previewEditor, imageMode = false,
    "Reload Preview", "Reload Wikitext preview", AllIcons.Actions.Refresh,
) {
    override fun actionPerformed(event: AnActionEvent) {
        previewEditor.reloadPreview()
    }
}

private class ZoomInAction(
    private val previewEditor: PrpPreviewBrowser,
) : ModeAction(
    previewEditor, imageMode = true,
    "Zoom In", "Zoom into the reference image", AllIcons.General.ZoomIn,
) {
    override fun actionPerformed(event: AnActionEvent) {
        previewEditor.zoomImage(1.25)
    }
}

private class ZoomOutAction(
    private val previewEditor: PrpPreviewBrowser,
) : ModeAction(
    previewEditor, imageMode = true,
    "Zoom Out", "Zoom out of the reference image", AllIcons.General.ZoomOut,
) {
    override fun actionPerformed(event: AnActionEvent) {
        previewEditor.zoomImage(1 / 1.25)
    }
}

private class ResetZoomAction(
    private val previewEditor: PrpPreviewBrowser,
) : ModeAction(
    previewEditor, imageMode = true,
    "Reset Zoom", "Fit the reference image to the pane", AllIcons.General.ActualZoom,
) {
    override fun actionPerformed(event: AnActionEvent) {
        previewEditor.resetImageZoom()
    }
}

private class SendToOcrAction(
    private val previewEditor: PrpPreviewBrowser,
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
