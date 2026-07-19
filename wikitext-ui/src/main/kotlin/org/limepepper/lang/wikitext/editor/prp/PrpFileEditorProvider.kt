package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.fileEditor.FileEditor
import com.intellij.openapi.fileEditor.FileEditorPolicy
import com.intellij.openapi.fileEditor.FileEditorProvider
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.impl.text.TextEditorProvider
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import org.limepepper.lang.wikitext.PrpFileType

/**
 * Provides an implementation of the intellij SDK FileEditorProvider
 * extension to be registered in the plugin.xml
 *
 * This provider accepts VirtualFile objects with a content_model of 'proofread-page' or have an extension 'prp'.
 *
 * Typically, the VirtualFile objects are synthetic and provided by the
 * wikisource VFS from sqlite backed storage; however, static local prp
 * files can be used to test the Provider is functional.
 */
class PrpFileEditorProvider : FileEditorProvider, DumbAware {
    override fun accept(
        project: Project,
        file: VirtualFile
    ): Boolean = file.fileType == PrpFileType

    override fun createEditor(
        project: Project,
        file: VirtualFile
    ): FileEditor {
        val textEditor = TextEditorProvider.getInstance().createEditor(project, file) as TextEditor

        return PrpFileEditor(project, textEditor, file)
    }

    override fun getEditorTypeId(): String = EDITOR_TYPE_ID

    override fun getPolicy(): FileEditorPolicy = FileEditorPolicy.HIDE_OTHER_EDITORS

    companion object {
        const val EDITOR_TYPE_ID = "proofread-page-editor"
    }
}
