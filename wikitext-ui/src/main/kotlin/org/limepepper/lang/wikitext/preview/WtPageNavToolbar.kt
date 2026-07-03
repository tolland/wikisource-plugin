package org.limepepper.lang.wikitext.preview

import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.DefaultActionGroup
import com.intellij.openapi.diagnostic.logger
import com.intellij.ui.JBColor
import com.intellij.util.ui.JBUI
import javax.swing.JComponent

private val NAV_LOG = logger<WtPageNavToolbar>()

/**
 * Button row across the top of the text-editor half of the split editor,
 * installed as the editor's header component (the same slot the find bar
 * uses). Holds page navigation for the transcription workflow: back/forward
 * move to the previous/next Page: of the same index — stubs for now.
 */
internal class WtPageNavToolbar(targetComponent: JComponent) {
    val component: JComponent

    init {
        val group = DefaultActionGroup(
            PreviousPageAction(),
            NextPageAction(),
        )
        val toolbar = ActionManager.getInstance()
            .createActionToolbar("WikitextPageNavToolbar", group, true)
        toolbar.targetComponent = targetComponent
        component = toolbar.component.apply {
            border = JBUI.Borders.customLineBottom(JBColor.border())
        }
    }
}

private class PreviousPageAction : AnAction(
    "Previous Page",
    "Open the previous page of this index",
    AllIcons.Actions.Back,
) {
    override fun actionPerformed(event: AnActionEvent) {
        // Stub: will resolve the preceding Page: sibling from the index
        // listing and open it in this split editor.
        NAV_LOG.info("Previous Page: not implemented yet")
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

private class NextPageAction : AnAction(
    "Next Page",
    "Open the next page of this index",
    AllIcons.Actions.Forward,
) {
    override fun actionPerformed(event: AnActionEvent) {
        // Stub: will resolve the following Page: sibling from the index
        // listing and open it in this split editor.
        NAV_LOG.info("Next Page: not implemented yet")
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}
