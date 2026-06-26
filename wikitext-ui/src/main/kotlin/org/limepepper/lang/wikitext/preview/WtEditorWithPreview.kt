package org.limepepper.lang.wikitext.preview

import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.ActionGroup
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.DefaultActionGroup
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.TextEditorWithPreview
import com.intellij.openapi.fileEditor.TextEditorWithPreview.Layout

class WtEditorWithPreview(
    textEditor: TextEditor,
    private val wtPreviewEditor: WtRenderPreviewBrowser,
) : TextEditorWithPreview(
    textEditor,
    wtPreviewEditor,
    "Wikitext Preview",
    Layout.SHOW_EDITOR_AND_PREVIEW,
) {
    override fun createRightToolbarActionGroup(): ActionGroup {
        return DefaultActionGroup(
            listOf(
                ReloadPreviewAction(wtPreviewEditor),
            ),
        )
    }
}

private class ReloadPreviewAction(
    private val previewEditor: WtRenderPreviewBrowser,
) : AnAction("Reload Preview", "Reload Wikitext preview", AllIcons.Actions.Refresh) {
    override fun actionPerformed(event: AnActionEvent) {
        previewEditor.reloadPreview()
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}
