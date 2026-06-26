package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileEditor.FileEditor
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile

/**
 * Access point for the bundled Swagger plugin's previews. The implementation lives in the optional
 * module (loaded only when `com.intellij.swagger` is present), so callers must treat a `null`
 * instance as "Swagger not installed" rather than reaching for another plugin's classloader.
 */
interface SwaggerPreviewSupport {
    fun createRedoc(file: VirtualFile, textEditor: TextEditor, project: Project): FileEditor

    fun createSwaggerUi(file: VirtualFile, textEditor: TextEditor, project: Project): FileEditor

    fun reload(preview: FileEditor, file: VirtualFile): Boolean

    companion object {
        fun getInstance(): SwaggerPreviewSupport? =
            ApplicationManager.getApplication().getService(SwaggerPreviewSupport::class.java)

        fun isAvailable(): Boolean = getInstance() != null
    }
}
