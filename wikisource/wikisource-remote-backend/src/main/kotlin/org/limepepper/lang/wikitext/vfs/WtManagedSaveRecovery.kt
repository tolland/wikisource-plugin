package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.impl.FileDocumentManagerImpl
import com.intellij.openapi.editor.ex.DocumentEx
import com.intellij.util.LocalTimeCounter
import com.intellij.openapi.application.ModalityState
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileWithId
import com.intellij.openapi.vfs.newvfs.persistent.PersistentFS
import com.intellij.openapi.vfs.newvfs.persistent.PersistentFSImpl

/** Compensation for PersistentFS's cache write/after-event on failed physical writes (262). */
internal object WtManagedSaveRecovery {
    fun invalidate(file: VirtualFile) {
        (PersistentFS.getInstance() as PersistentFSImpl)
            .cleanPersistedContent((file as VirtualFileWithId).id)
    }

    fun failed(file: VirtualFile) {
        val documents = FileDocumentManager.getInstance()
        val document = documents.getCachedDocument(file)
        val failedText = document?.text
        val app = ApplicationManager.getApplication()
        // PersistentFS finishes its after-event after our stream throws. Restore
        // tracking afterwards, without changing text or adding an undo command.
        app.invokeLater({
            if (!file.isValid) return@invokeLater
            app.runWriteAction {
                invalidate(file)
                if (document != null && document.text == failedText && documents.getFile(document) == file) {
                    (document as DocumentEx).setModificationStamp(LocalTimeCounter.currentTime())
                    (documents as FileDocumentManagerImpl).markDocumentUnsaved(document, true)
                }
            }
        }, ModalityState.nonModal())
    }
}
