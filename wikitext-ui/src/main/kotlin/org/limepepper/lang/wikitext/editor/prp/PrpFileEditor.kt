package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.TextEditorWithPreview
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile

/**
 * Provides an implementation of FileEditor, suitable for use by [PrpFileEditorProvider] via its' [com.intellij.openapi.fileEditor.FileEditorProvider.createEditor] method.
 */
class PrpFileEditor(
    project: Project,
    editor: TextEditor,
    file: VirtualFile,
) : TextEditorWithPreview(
    PrpTextEditor(project, editor),
    PrpPreviewBrowser(file),
) {
    init {
        // Initialize TextEditorWithPreview's lazy UI before disposal-sensitive editor switching can occur.
        component
    }
}
