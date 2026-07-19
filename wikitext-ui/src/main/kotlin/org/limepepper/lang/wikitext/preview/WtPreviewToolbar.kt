package org.limepepper.lang.wikitext.preview

import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.DefaultActionGroup
import com.intellij.ui.JBColor
import com.intellij.util.ui.JBUI
import javax.swing.JComponent

/**
 * Inset toolbar running along the top of the preview pane (replacing the
 * hover/floating buttons). The reference-image actions (mode toggle, zoom,
 * OCR) belong to the proofread-page editor's toolbar in
 * [org.limepepper.lang.wikitext.editor.prp.PrpPreviewToolbar].
 */
internal class WtPreviewToolbar(
    previewBrowser: WtRenderPreviewBrowser,
) {
    val component: JComponent

    init {
        val group = DefaultActionGroup(
            ReloadPreviewAction(previewBrowser),
        )
        val toolbar = ActionManager.getInstance()
            .createActionToolbar("WikitextPreviewToolbar", group, true)
        toolbar.targetComponent = previewBrowser.component
        component = toolbar.component.apply {
            border = JBUI.Borders.customLineBottom(JBColor.border())
        }
    }
}

private class ReloadPreviewAction(
    private val previewEditor: WtRenderPreviewBrowser,
) : AnAction("Reload Preview", "Reload Wikitext preview", AllIcons.Actions.Refresh) {
    override fun actionPerformed(event: AnActionEvent) {
        previewEditor.reloadPreview()
    }
}
