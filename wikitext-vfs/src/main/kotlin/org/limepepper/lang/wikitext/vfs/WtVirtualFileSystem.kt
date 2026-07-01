package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileListener
import com.intellij.openapi.vfs.VirtualFileSystem
import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.io.IOException
import java.nio.file.Path
import java.util.concurrent.ConcurrentHashMap

/**
 * `wikisource://` [VirtualFileSystem] backed by the wtbot FastAPI sidecar.
 *
 * Path scheme mirrors the VFS API:
 *   /                                         root (all sites)
 *   /{family}/{code}/                         site root
 *   /{family}/{code}/{Index title}/           index directory
 *   /{family}/{code}/{Index title}/Pages/     pages container
 *   /{family}/{code}/{Index title}/Pages/{Page title}   page file
 *   /{family}/{code}/{Index title}/{File title}/        file directory
 *   /{family}/{code}/{Index title}/{File title}/wikitext
 *   /{family}/{code}/{Index title}/{File title}/blob
 *
 * [WtVirtualFile] instances are cached by path so callers always get the
 * same instance for the same path (IntelliJ VFS contract).
 */
class WtVirtualFileSystem : VirtualFileSystem() {

    companion object {
        const val PROTOCOL: String = "wikisource"
    }

    private val cache = ConcurrentHashMap<String, WtVirtualFile>()

    /**
     * Return an existing cached instance or create a new one. Does NOT hit
     * the network — callers supply the metadata they already have.
     */
    fun getOrCreate(
        path: String,
        name: String,
        isDir: Boolean,
        parent: WtVirtualFile? = null,
        stableId: Long? = null,
        revid: Long? = null,
    ): WtVirtualFile = cache.getOrPut(path) {
        WtVirtualFile(this, name, path, isDir, parent, stableId, revid)
    }.also { if (parent != null) it.setParent(parent) }

    /** Stat the backend and return a [WtVirtualFile] if the path exists. */
    override fun findFileByPath(path: String): VirtualFile? {
        val cached = cache[path]
        if (cached != null) return cached
        return try {
            val stat = WtVfsService.instance.backend.stat(path)
            if (!stat.exists) return null
            getOrCreate(
                path = path,
                name = stat.name ?: path.substringAfterLast('/').ifEmpty { "/" },
                isDir = stat.kind == NodeKind.directory,
                stableId = stat.stableId,
                revid = stat.revid,
            )
        } catch (_: VfsBackendException) {
            null
        }
    }

    override fun getProtocol(): String = PROTOCOL

    /**
     * Re-stats every cached [WtVirtualFile] and invalidates its content/children
     * cache when the backend's revid has moved on, so the next access re-fetches.
     */
    override fun refresh(asynchronous: Boolean) {
        val doRefresh = Runnable {
            val backend = WtVfsService.instance.backend
            for (file in cache.values) {
                try {
                    val stat = backend.stat(file.path)
                    if (!stat.exists) continue
                    if (stat.revid != file.revid) {
                        file.cachedContent = null
                    }
                    file.cachedChildren = null
                } catch (_: VfsBackendException) {
                    // Backend unreachable — leave cached state as-is.
                }
            }
        }
        if (asynchronous) {
            ApplicationManager.getApplication().executeOnPooledThread(doRefresh)
        } else {
            doRefresh.run()
        }
    }

    override fun refreshAndFindFileByPath(path: String): VirtualFile? = findFileByPath(path)

    override fun addVirtualFileListener(listener: VirtualFileListener) {}
    override fun removeVirtualFileListener(listener: VirtualFileListener) {}

    override fun deleteFile(requestor: Any?, vFile: VirtualFile) { throw IOException("delete not supported") }
    override fun moveFile(requestor: Any?, vFile: VirtualFile, newParent: VirtualFile) { throw IOException("move not supported") }
    override fun renameFile(requestor: Any?, vFile: VirtualFile, newName: String) { throw IOException("rename not supported") }
    override fun createChildFile(requestor: Any?, vDir: VirtualFile, fileName: String): VirtualFile { throw IOException("createChildFile not supported") }
    override fun createChildDirectory(requestor: Any?, vDir: VirtualFile, dirName: String): VirtualFile { throw IOException("createChildDirectory not supported") }
    override fun copyFile(requestor: Any?, virtualFile: VirtualFile, newParent: VirtualFile, copyName: String): VirtualFile { throw IOException("copyFile not supported") }

    override fun isReadOnly(): Boolean = true
    override fun isCaseSensitive(): Boolean = true
    override fun isValidName(name: String): Boolean = name.isNotEmpty()
    override fun getNioPath(file: VirtualFile): Path? = null
}
