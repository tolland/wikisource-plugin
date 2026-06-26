package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.fileEditor.FileEditor
import com.intellij.openapi.fileEditor.FileEditorPolicy
import com.intellij.openapi.fileEditor.FileEditorProvider
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.impl.text.TextEditorProvider
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile

class WtPreviewEditorProvider : FileEditorProvider, DumbAware {
    override fun accept(project: Project, file: VirtualFile): Boolean {
        return acceptsFile(file)
    }

    override fun createEditor(project: Project, file: VirtualFile): FileEditor {
        val textEditor = TextEditorProvider.getInstance().createEditor(project, file) as TextEditor
        val previewEditor = WtRenderPreviewBrowser(project, file, textEditor)

        return OpenApiEditorWithPreview(
            textEditor,
            previewEditor,
        )
    }

    override fun getEditorTypeId(): String = EDITOR_TYPE_ID

    override fun getPolicy(): FileEditorPolicy = FileEditorPolicy.HIDE_OTHER_EDITORS

    companion object {
        const val EDITOR_TYPE_ID = "scalar-openapi-preview"

        fun acceptsFile(file: VirtualFile): Boolean {
            val extension = file.extension?.lowercase()
            if (extension !in setOf("yaml", "yml", "json")) {
                return false
            }

            return hasOpenApiSpecificationMarker(file)
        }
    }
}