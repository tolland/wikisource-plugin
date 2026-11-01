package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.editor.Document
import com.intellij.openapi.fileEditor.FileDocumentManagerListener
import com.intellij.openapi.vfs.VirtualFile

/** Accept a newer read revision only when the Document actually reloads its contents. */
class WtManagedDocumentListener : FileDocumentManagerListener {
    override fun fileContentReloaded(file: VirtualFile, document: Document) {
        (file.fileSystem as? WtManagedBackendFileSystem)?.contentReloaded(file)
    }
}
