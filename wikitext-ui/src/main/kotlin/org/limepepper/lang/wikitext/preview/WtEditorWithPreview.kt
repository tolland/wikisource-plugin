package org.limepepper.lang.wikitext.preview

import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.ActionGroup
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.DefaultActionGroup
import com.intellij.openapi.actionSystem.ToggleAction
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
    init {
        // Initialize TextEditorWithPreview's lazy UI before disposal-sensitive editor switching can occur.
        component
    }

    override fun createRightToolbarActionGroup(): ActionGroup {
        return DefaultActionGroup(
            listOf(
                ToggleReferenceImageAction(wtPreviewEditor),
                ReloadPreviewAction(wtPreviewEditor),
            ),
        )
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

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

private class ReloadPreviewAction(
    private val previewEditor: WtRenderPreviewBrowser,
) : AnAction("Reload Preview", "Reload Wikitext preview", AllIcons.Actions.Refresh) {
    override fun actionPerformed(event: AnActionEvent) {
        previewEditor.reloadPreview()
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}
