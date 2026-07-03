package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.editor.ex.EditorEx
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.TextEditorWithPreview
import com.intellij.openapi.fileEditor.TextEditorWithPreview.Layout

/**
 * The wikitext split editor. Both halves carry their own inset toolbar
 * instead of actions on the platform's hover toolbar: the preview pane owns
 * [WtPreviewToolbar] (mode toggle / reload / zoom / OCR) and the text editor
 * gets [WtPageNavToolbar] as its header component (page back/forward).
 */
class WtEditorWithPreview(
    textEditor: TextEditor,
    wtPreviewEditor: WtRenderPreviewBrowser,
) : TextEditorWithPreview(
    textEditor,
    wtPreviewEditor,
    "Wikitext Preview",
    Layout.SHOW_EDITOR_AND_PREVIEW,
) {
    init {
        // Initialize TextEditorWithPreview's lazy UI before disposal-sensitive editor switching can occur.
        component

        (textEditor.editor as? EditorEx)?.let { editor ->
            val navBar = WtPageNavToolbar(editor.component).component
            // Permanent so the row comes back when the find bar (which shares
            // the header slot) is closed.
            editor.permanentHeaderComponent = navBar
            editor.headerComponent = navBar
        }
    }
}
