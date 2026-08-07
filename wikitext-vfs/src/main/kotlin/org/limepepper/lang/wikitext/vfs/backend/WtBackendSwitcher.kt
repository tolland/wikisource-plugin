package org.limepepper.lang.wikitext.vfs.backend

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.project.ProjectManager
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.vfs.VirtualFileManager
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.WtVirtualFileSystem
import org.limepepper.lang.wikitext.vfs.settings.OcrCatalogService

/**
 * Rebuilds the plugin-side view of the VFS after the backend has been pointed
 * at a different wtbot sidecar.
 *
 * The sidecar's SQLite database *is* the state; everything the plugin holds is
 * a cache of it that can be thrown away and refetched cheaply. So the job here
 * is deliberately blunt — drop the caches, re-stat what was cached, and let the
 * next access refill from the new sidecar. The only parts that need care are
 * the ones the user can see: paths that don't exist on the new backend must not
 * stay open showing the old backend's text, and unsaved edits must not be
 * silently pushed to a sidecar they were never based on.
 */
internal object WtBackendSwitcher {

    private val LOG = Logger.getInstance(WtBackendSwitcher::class.java)

    /**
     * Asks about `wikisource://` documents with unsaved changes, *before* the
     * backend is switched, so "Save" still writes them to the sidecar they
     * were read from. Their cached revid is the conflict token for that
     * sidecar alone, so carrying them across would either spuriously conflict
     * or, worse, land an edit on a same-named page of a different wiki.
     *
     * Call on the EDT. Returns false if the user cancelled the switch.
     */
    fun confirmPendingEdits(): Boolean {
        val documents = FileDocumentManager.getInstance()
        val unsaved = documents.unsavedDocuments.filter { documents.getFile(it) is WtVirtualFile }
        if (unsaved.isEmpty()) return true

        val names = unsaved.mapNotNull { documents.getFile(it)?.name }.sorted()
        val choice = Messages.showYesNoCancelDialog(
            buildString {
                appendLine("These wikisource files have unsaved changes:")
                appendLine()
                names.take(10).forEach { appendLine("    $it") }
                if (names.size > 10) appendLine("    … and ${names.size - 10} more")
                appendLine()
                append("Save them to the current backend before switching?")
            },
            "Switch wtbot Backend",
            "Save",
            "Discard",
            "Cancel",
            Messages.getWarningIcon(),
        )
        return when (choice) {
            Messages.YES -> {
                ApplicationManager.getApplication().runWriteAction {
                    unsaved.forEach { documents.saveDocument(it) }
                }
                true
            }
            // Discard: the reload pass below replaces the buffers with the new
            // backend's content, dropping the edits.
            Messages.NO -> true
            else -> false
        }
    }

    /**
     * Invalidates every cached file against the new backend, closes editors on
     * paths it doesn't have, reloads the ones it does, and finally announces
     * [WtVfsService.BACKEND_SWITCHED].
     *
     * Network work happens on a pooled thread; editor surgery on the EDT.
     */
    fun rebuildAfterSwitch(baseUrl: String) {
        ApplicationManager.getApplication().executeOnPooledThread {
            val fileSystem = VirtualFileManager.getInstance()
                .getFileSystem(WtVirtualFileSystem.PROTOCOL) as? WtVirtualFileSystem

            val outcome = fileSystem?.rebindToCurrentBackend() ?: RebindOutcome.EMPTY

            for (project in ProjectManager.getInstance().openProjects) {
                // Discovered per site from the old sidecar; the new one may
                // have entirely different OCR backends configured.
                OcrCatalogService.getInstance(project).clearCache()
            }

            ApplicationManager.getApplication().invokeLater {
                closeEditorsFor(outcome.missing)
                reloadOpenDocuments(outcome.surviving)
                outcome.missing.forEach { it.markInvalid() }
                ApplicationManager.getApplication().messageBus
                    .syncPublisher(WtVfsService.BACKEND_SWITCHED)
                    .backendSwitched(baseUrl)
            }
        }
    }

    /**
     * Editors are closed rather than left showing stale text: the file is
     * about to become invalid, and an editor over an invalid [WtVirtualFile]
     * would fail its next read with no explanation the user can act on.
     */
    private fun closeEditorsFor(missing: List<WtVirtualFile>) {
        if (missing.isEmpty()) return
        for (project in ProjectManager.getInstance().openProjects) {
            if (project.isDisposed) continue
            val editors = FileEditorManager.getInstance(project)
            missing.filter { editors.isFileOpen(it) }.forEach { editors.closeFile(it) }
        }
        LOG.info("closed editors for ${missing.size} path(s) absent from the new backend")
    }

    /**
     * Only files the platform already has a document for need reloading —
     * everything else refetches lazily on next access, which is the whole
     * point of dropping the caches.
     */
    private fun reloadOpenDocuments(surviving: List<WtVirtualFile>) {
        val documents = FileDocumentManager.getInstance()
        val loaded = surviving.filter { !it.isDirectory && documents.getCachedDocument(it) != null }
        if (loaded.isEmpty()) return
        documents.reloadFiles(*loaded.toTypedArray())
    }
}

/** What a re-stat against the newly installed backend found. */
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
