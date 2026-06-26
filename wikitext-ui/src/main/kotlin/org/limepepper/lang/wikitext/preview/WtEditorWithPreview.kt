package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.actionSystem.ActionGroup
import com.intellij.openapi.actionSystem.DefaultActionGroup
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.TextEditorWithPreview
import com.intellij.openapi.fileEditor.TextEditorWithPreview.Layout

class WtEditorWithPreview (
    textEditor: TextEditor,
    private val openApiPreviewEditor: OpenApiPreviewBrowser,
) : TextEditorWithPreview(
    textEditor,
    openApiPreviewEditor,
    "Wikitext Preview",
    Layout.SHOW_EDITOR_AND_PREVIEW,
) {
    override fun createRightToolbarActionGroup(): ActionGroup {
        return DefaultActionGroup(
            listOf(
                ReloadPreviewAction(openApiPreviewEditor),
                SwitchPreviewRendererAction(openApiPreviewEditor),
            ),
        )
    }
}
