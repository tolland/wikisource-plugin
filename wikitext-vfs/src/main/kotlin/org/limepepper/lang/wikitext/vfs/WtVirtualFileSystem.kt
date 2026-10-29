package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileListener
import com.intellij.openapi.vfs.VirtualFileSystem
import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.RebindOutcome
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.io.IOException
import java.nio.file.Path
import java.util.concurrent.ConcurrentHashMap

private val LOG = Logger.getInstance(WtVirtualFileSystem::class.java)

/**
 * `wikisource://` [VirtualFileSystem] backed by the wtbot FastAPI sidecar.
 *
 * Path scheme mirrors the VFS API (see [WtPaths]):
 *   /                                         root (all sites)
 *   /{family}/{code}                          site: the namespaces holding titles
 *   /{family}/{code}/{namespace}              namespace container (`(Main)` for main)
 *   /{family}/{code}/{ns}/{title...}          a title: a directory holding its
 *                                             subpages and its aspect files
 *   .../{title}/@wikitext                     the title's content (the file you edit)
 *   .../{title}/@props                        its properties (read-only JSON)
 *   .../{Index title}/@pages                  the Page: titles an Index paginates
 *   /{family}/{code}/Page/{Book.djvu}/{n}     a Page: -- listed by @pages, not nested in it
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
        contentModel: String? = null,
        qualityLevel: Int? = null,
        dirty: Boolean = false,
        hasReferenceImage: Boolean = false,
        placeholder: Boolean = false,
        length: Long? = null,
        timestamp: String? = null,
        hasChildren: Boolean = false,
        aspects: List<String> = emptyList(),
    ): WtVirtualFile = cache.getOrPut(path) {
        WtVirtualFile(
            this, name, path, isDir, parent, stableId, revid, contentModel,
            qualityLevel, dirty, hasReferenceImage, placeholder, length, timestamp,
            hasChildren, aspects,
        )
    }.also {
        if (parent != null) it.setParent(parent)
        // Instances are cached by path; every sighting carries the freshest
        // decoration metadata, so re-apply it to the cached instance too.
        it.updateMeta(
            qualityLevel, dirty, hasReferenceImage, placeholder, length, timestamp,
            hasChildren, aspects,
        )
    }

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
                contentModel = stat.contentModel,
                qualityLevel = stat.qualityLevel,
                dirty = stat.dirty,
                hasReferenceImage = stat.hasReferenceImage,
                placeholder = stat.placeholder,
                length = stat.length,
                timestamp = stat.timestamp,
                hasChildren = stat.hasChildren,
                aspects = stat.aspects,
            )
        } catch (_: VfsBackendException) {
            null
        }
    }

    override fun getProtocol(): String = PROTOCOL

    /**
     * Re-stats every cached [WtVirtualFile] in one batched call and invalidates
     * its content/children cache when the backend's revid has moved on, so the
     * next access re-fetches. Uses [VfsBackend.statBulk] rather than one
     * request per file — at real-library scale (thousands of cached pages)
     * a per-file loop here would be thousands of round trips.
     */
    override fun refresh(asynchronous: Boolean) {
        val doRefresh = Runnable {
            val files = cache.values.toList()
            if (files.isEmpty()) return@Runnable
            try {
                val stats = WtVfsService.instance.backend.statBulk(files.map { it.path })
                val changed = files.zip(stats)
                    .filter { (file, stat) -> stat.exists && file.invalidateIfStale(stat) }
                    .map { it.first }
                reloadOpenDocuments(changed)
            } catch (_: VfsBackendException) {
                // Backend unreachable — leave cached state as-is.
            }
        }
        if (asynchronous) {
            ApplicationManager.getApplication().executeOnPooledThread(doRefresh)
        } else {
            doRefresh.run()
        }
    }

    /**
     * Dropping [WtVirtualFile.cachedContent] is not enough for a file already
     * open in an editor: the platform keeps its own Document and only re-reads
     * it when told to. Documents with unsaved edits are left alone -- a refresh
     * must not discard what the user is typing.
     */
    private fun reloadOpenDocuments(changed: List<WtVirtualFile>) {
        if (changed.isEmpty()) return
        ApplicationManager.getApplication().invokeLater {
            val documents = FileDocumentManager.getInstance()
            val stale = changed.filter {
                it.isValid && documents.getCachedDocument(it) != null && !documents.isFileModified(it)
            }
            if (stale.isNotEmpty()) documents.reloadFiles(*stale.toTypedArray())
        }
    }

    override fun refreshAndFindFileByPath(path: String): VirtualFile? = findFileByPath(path)

    /** Every [WtVirtualFile] handed out so far, in no particular order. */
    fun cachedFiles(): List<WtVirtualFile> = cache.values.toList()

    /**
     * Drops every cached file's content and children, then re-stats them all
     * against whatever backend [WtVfsService] currently holds — the rebuild
     * after the sidecar has been switched underneath us.
     *
     * Instances are deliberately *not* evicted wholesale: open editors and the
     * tool window tree hold them, and the VFS contract requires one instance
     * per path, so dropping the map would fork identities the moment a path
     * were looked up again. Only paths the new backend doesn't have are
     * evicted, so a later [findFileByPath] can mint a fresh valid instance if
     * one ever reappears.
     *
     * Blocking; call off the EDT.
     */
    internal fun rebindToCurrentBackend(): RebindOutcome {
        val files = cache.values.toList()
        files.forEach { it.dropCaches() }
        if (files.isEmpty()) return RebindOutcome.EMPTY

        val stats = try {
            WtVfsService.instance.backend.statBulk(files.map { it.path })
        } catch (e: VfsBackendException) {
            // New backend unreachable. Caches are already dropped, so nothing
            // stale survives; leave the files valid and let the next access
            // surface the connection error the normal way.
            LOG.warn("re-stat after backend switch failed; caches dropped, files kept", e)
            return RebindOutcome(files, emptyList())
        }

        val surviving = mutableListOf<WtVirtualFile>()
        val missing = mutableListOf<WtVirtualFile>()
        for ((file, stat) in files.zip(stats)) {
            if (stat.exists) {
                file.invalidateIfStale(stat)
                surviving += file
            } else {
                cache.remove(file.path, file)
                missing += file
            }
        }
        return RebindOutcome(surviving, missing)
    }

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
