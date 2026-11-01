package org.limepepper.lang.wikitext.vfs.backend

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.project.ProjectManager
import com.intellij.openapi.ui.Messages
import org.limepepper.lang.wikitext.vfs.WtManagedBackendFileSystem
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.settings.OcrCatalogService

/** Rebind open managed documents after an explicit endpoint change. */
internal object WtBackendSwitcher {
    private var discardOnSwitch = emptySet<com.intellij.openapi.editor.Document>()
    fun confirmPendingEdits(): Boolean {
        val documents = FileDocumentManager.getInstance()
        val unsaved = documents.unsavedDocuments.filter {
            documents.getFile(it)?.fileSystem is WtManagedBackendFileSystem
        }
        discardOnSwitch = emptySet()
        if (unsaved.isEmpty()) return true
        return when (Messages.showYesNoCancelDialog(
            "Save ${unsaved.size} modified Wikisource document(s) to the current backend before switching?",
            "Switch wtbot Backend", "Save", "Discard", "Cancel", Messages.getWarningIcon())) {
            Messages.YES -> {
                unsaved.forEach { documents.saveDocument(it) }
                unsaved.none { document ->
                    val file = documents.getFile(document)
                    documents.isDocumentUnsaved(document) ||
                        (file?.fileSystem as? WtManagedBackendFileSystem)?.hasFailedWrite(file) == true
                }
            }
            Messages.NO -> { discardOnSwitch = unsaved.toSet(); true }
            else -> false
        }
    }

    fun rebuildAfterSwitch(baseUrl: String) {
        val projects = ProjectManager.getInstance().openProjects
        val files = projects.flatMap { FileEditorManager.getInstance(it).openFiles.toList() }
            .filter { it.fileSystem is WtManagedBackendFileSystem }.distinct()
        val discard = discardOnSwitch
        discardOnSwitch = emptySet()
        ApplicationManager.getApplication().executeOnPooledThread {
            files.forEach { file ->
                val fs = file.fileSystem as WtManagedBackendFileSystem
                fs.resetConnection(file)
                try {
                    fs.refreshFile(file, false)
                    ApplicationManager.getApplication().invokeAndWait {
                        val documents = FileDocumentManager.getInstance()
                        val document = documents.getCachedDocument(file)
                        if (document in discard && file.isValid) documents.reloadFromDisk(requireNotNull(document))
                    }
                } catch (_: VfsBackendException) { /* Retain cached text until the new service recovers. */ }
            }
            projects.filterNot { it.isDisposed }.forEach { OcrCatalogService.getInstance(it).clearCache() }
            ApplicationManager.getApplication().invokeLater {
                ApplicationManager.getApplication().messageBus.syncPublisher(WtVfsService.BACKEND_SWITCHED).backendSwitched(baseUrl)
            }
        }
    }
}


/** Result retained for the unregistered legacy-filesystem regression fixtures. */
internal data class RebindOutcome(
    /** Cached files the new backend also has — kept, with caches dropped. */
    val surviving: List<WtVirtualFile>,
    /** Cached files the new backend does not have — to be closed and invalidated. */
    val missing: List<WtVirtualFile>,
) {
    companion object {
        val EMPTY = RebindOutcome(emptyList(), emptyList())
    }
}
