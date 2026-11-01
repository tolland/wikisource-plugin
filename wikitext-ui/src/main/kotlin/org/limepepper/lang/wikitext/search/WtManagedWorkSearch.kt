package org.limepepper.lang.wikitext.search

import com.intellij.openapi.components.Service
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileManager
import org.limepepper.lang.wikitext.vfs.WtAttachedWork
import org.limepepper.lang.wikitext.vfs.WtWorkAttachments
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.io.IOException

/** Unregistered search prototype. Only explicit project attachments can supply files. */
@Service(Service.Level.PROJECT)
class WtManagedWorkSearch(private val project: Project) {
    private val attachments get() = project.getService(WtWorkAttachments::class.java)
    private data class Snapshot(val backend: VfsBackend, val works: List<WtAttachedWork>, val files: Set<VirtualFile>)
    @Volatile private var snapshot: Snapshot? = null

    fun cachedFiles(): Set<VirtualFile> = snapshot?.takeIf {
        it.backend === WtVfsService.instance.backend && it.works == attachments.attachments()
    }?.files.orEmpty().filterTo(linkedSetOf()) { it.isValid }

    /** Called during background root discovery, never while constructing the scope chooser. */
    @Synchronized
    fun loadFiles(): Set<VirtualFile> {
        val backend = WtVfsService.instance.backend
        val works = attachments.attachments()
        snapshot?.takeIf { it.backend === backend && it.works == works }?.let { return cachedFiles() }
        return try {
            works.forEach { attachments.checkAvailable(it, backend) }
            val manager = VirtualFileManager.getInstance()
            val files = works.flatMap { it.content }.distinct().mapTo(linkedSetOf()) { address ->
                ProgressManager.checkCanceled()
                manager.findFileByUrl(address.url)
                    ?: throw IOException("Cannot resolve work content: ${address.backendPath}")
            }
            if (backend !== WtVfsService.instance.backend) throw IOException("Backend changed while loading work")
            if (works != attachments.attachments()) throw IOException("Attachments changed while loading work files")
            snapshot = Snapshot(backend, works, files)
            Logger.getInstance(javaClass).info("Managed attached work content files=${files.size}")
            files
        } catch (failure: IOException) {
            Logger.getInstance(javaClass).info("Managed work unavailable: ${failure.message}")
            emptySet()
        }
    }
}
