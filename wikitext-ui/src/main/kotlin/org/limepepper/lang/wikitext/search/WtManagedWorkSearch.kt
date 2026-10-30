package org.limepepper.lang.wikitext.search

import com.intellij.openapi.components.Service
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileManager
import org.limepepper.lang.wikitext.vfs.WtManagedAddress
import org.limepepper.lang.wikitext.vfs.WtManagedWork
import org.limepepper.lang.wikitext.vfs.discoverManagedWork
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.io.IOException

/** Project-local snapshot: indexing may load it; the scope chooser only reads it. */
@Service(Service.Level.PROJECT)
class WtManagedWorkSearch {
    private data class Snapshot(val backend: VfsBackend, val work: WtManagedWork, val files: Set<VirtualFile>)
    @Volatile private var snapshot: Snapshot? = null

    fun cachedFiles(): Set<VirtualFile> = snapshot?.takeIf {
        it.backend === WtVfsService.instance.backend
    }?.files.orEmpty().filterTo(linkedSetOf()) { it.isValid }

    /** Called during background root discovery, never while constructing the scope chooser. */
    @Synchronized
    fun loadFiles(): Set<VirtualFile> {
        val backend = WtVfsService.instance.backend
        snapshot?.takeIf { it.backend === backend }?.let { return cachedFiles() }
        return try {
            val work = discoverManagedWork(backend, WtManagedAddress.fromPath(SEED_PATH))
            val manager = VirtualFileManager.getInstance()
            val files = work.content.mapTo(linkedSetOf()) { address ->
                ProgressManager.checkCanceled()
                manager.findFileByUrl(address.url)
                    ?: throw IOException("Cannot resolve work content: ${address.backendPath}")
            }
            if (backend !== WtVfsService.instance.backend) throw IOException("Backend changed while loading work")
            snapshot = Snapshot(backend, work, files)
            Logger.getInstance(javaClass).info("Managed work indexed roots: ${work.index.url}, content files=${files.size}")
            files
        } catch (failure: IOException) {
            Logger.getInstance(javaClass).info("Managed work unavailable: ${failure.message}")
            emptySet()
        }
    }

    companion object {
        // A single work for this migration slice; attachment selection follows independently.
        const val SEED_PATH = "/mywikisource/en/Page/Stevenson-Persuasive Definitions-1938.pdf/13/@wikitext"
    }
}
