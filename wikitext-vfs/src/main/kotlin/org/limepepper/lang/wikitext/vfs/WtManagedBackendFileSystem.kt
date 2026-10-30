package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.util.io.FileAttributes
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileManager
import com.intellij.openapi.vfs.newvfs.NewVirtualFileSystem
import com.intellij.openapi.vfs.newvfs.RefreshQueue
import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.StatResult
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import org.limepepper.lang.wikitext.vfs.backend.WriteStatus
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.OutputStream
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap

/** Managed file objects backed by wtbot; the existing wikisource:// implementation stays independent. */
class WtManagedBackendFileSystem : NewVirtualFileSystem() {
    private data class ReadVersion(val backend: VfsBackend, val revid: Long?)
    private val readVersions = ConcurrentHashMap<String, ReadVersion>()
    private val metadata = ConcurrentHashMap<String, StatResult>()
    private val backend: VfsBackend get() = WtVfsService.instance.backend

    override fun getProtocol(): String = WtManagedAddress.PROTOCOL
    override fun isCaseSensitive(): Boolean = true
    override fun isReadOnly(): Boolean = false
    override fun extractRootPath(normalizedPath: String): String = address(normalizedPath).rootPath
    override fun findFileByPath(path: String): VirtualFile? =
        findFileByPath(this, address(path).backendPath)?.also {
            val state = metadata[it.path] ?: stat(it)
            // Managed flags survive IDE restarts. Correct earlier read-only
            // records via VFS events, which also update cached Documents.
            if (state.exists && it.isWritable != state.writable) it.refresh(true, false)
        }
    override fun findFileByPathIfCached(path: String): VirtualFile? = findFileByPathIfCached(this, address(path).backendPath)
    override fun refreshAndFindFileByPath(path: String): VirtualFile? {
        // Refresh a known ancestor as well: the requested child may be newly created.
        findFileByPathIfCached(path)?.refresh(false, false)
            ?: findFileByPathIfCached(address(path).rootPath)?.refresh(false, true)
        return findFileByPath(path)
    }

    override fun refresh(asynchronous: Boolean) {
        val roots = com.intellij.openapi.vfs.newvfs.ManagingFS.getInstance().getRoots(this)
        if (roots.isNotEmpty()) RefreshQueue.getInstance().refresh(asynchronous, true, null, *roots)
    }

    private fun address(path: String) = WtManagedAddress.fromPath(path)
    private fun stat(file: VirtualFile): StatResult {
        val resource = address(file.path)
        val result = if (resource.isFamilyContainer) {
            // The API jumps directly from / to /family/code. Managed VFS needs
            // a real intermediate directory for each slash-separated segment.
            val exists = backend.listChildren("/").children.any {
                address(it.path).familyName == resource.familyName
            }
            StatResult(resource.backendPath, exists, resource.familyName, NodeKind.directory)
        } else backend.stat(resource.backendPath)
        metadata[file.path] = result
        return result
    }

    /** No I/O: file-type selection can happen on the EDT. */
    fun cachedMetadata(file: VirtualFile): StatResult? = metadata[file.path]

    override fun exists(file: VirtualFile): Boolean = stat(file).exists
    override fun isDirectory(file: VirtualFile): Boolean = stat(file).kind == NodeKind.directory
    override fun isWritable(file: VirtualFile): Boolean = stat(file).writable
    override fun getTimeStamp(file: VirtualFile): Long = stat(file).timestamp?.toLongOrNull() ?: 0
    override fun getLength(file: VirtualFile): Long = stat(file).length ?: 0
    override fun getAttributes(file: VirtualFile): FileAttributes? {
        val state = stat(file)
        if (!state.exists) return null
        return FileAttributes(state.kind == NodeKind.directory, false, false, false,
            state.length ?: 0, state.timestamp?.toLongOrNull() ?: 0, state.writable)
    }

    override fun list(file: VirtualFile): Array<String> {
        val resource = address(file.path)
        val path = resource.backendPath
        if (path == "/") {
            return backend.listChildren("/").children.map { address(it.path).familyName }.distinct().toTypedArray()
        }
        if (resource.isFamilyContainer) {
            val prefix = "$path/"
            return backend.listChildren("/").children.filter { it.path.startsWith(prefix) }
                .map { it.path.removePrefix(prefix) }.toTypedArray()
        }
        val prefix = path.trimEnd('/') + "/"
        return backend.listChildren(path).children.map { child ->
            // @pages is a graph view: its children live at canonical Page: paths.
            // Do not mint duplicate managed identities by pretending they are nested files.
            val name = child.path.removePrefix(prefix)
            if (!child.path.startsWith(prefix) || name.isEmpty() || '/' in name) {
                throw IOException("Non-hierarchical VFS child ${child.path} under $path; use its canonical path")
            }
            metadata[child.path] = StatResult(path = child.path, exists = true, name = child.name,
                kind = child.kind, stableId = child.stableId, revid = child.revid,
                length = child.length, timestamp = child.timestamp, writable = child.writable,
                contentModel = child.contentModel, qualityLevel = child.qualityLevel, dirty = child.dirty,
                hasReferenceImage = child.hasReferenceImage, placeholder = child.placeholder,
                hasChildren = child.hasChildren, aspects = child.aspects)
            name
        }.toTypedArray()
    }

    override fun contentsToByteArray(file: VirtualFile): ByteArray {
        val current = backend
        val content = current.readContent(address(file.path).backendPath)
        readVersions[file.path] = ReadVersion(current, content.revid)
        return content.decodeContent()
    }

    override fun getInputStream(file: VirtualFile) = ByteArrayInputStream(contentsToByteArray(file))

    override fun getOutputStream(file: VirtualFile, requestor: Any?, modStamp: Long, timeStamp: Long): OutputStream {
        val current = backend
        val version = readVersions[file.path]
            ?: ReadVersion(current, current.stat(address(file.path).backendPath).revid)
        if (version.backend !== current) throw IOException("Backend changed since this file was read; reload before saving")
        return object : ByteArrayOutputStream() {
            override fun close() {
                super.close()
                if (backend !== current) throw IOException("Backend changed before save; reload before saving")
                val result = current.writeContent(address(file.path).backendPath,
                    Base64.getEncoder().encodeToString(toByteArray()), version.revid)
                when (result.status) {
                    WriteStatus.ok -> {
                        readVersions[file.path] = ReadVersion(current, result.newRevid)
                        metadata.computeIfPresent(file.path) { _, previous ->
                            previous.copy(revid = result.newRevid, length = size().toLong(), dirty = true,
                                timestamp = System.currentTimeMillis().toString())
                        }
                        // Both protocols temporarily expose the same resource. Invalidate
                        // only its legacy cache and reload documents without unsaved edits.
                        (VirtualFileManager.getInstance().getFileSystem(WtVirtualFileSystem.PROTOCOL)
                            as? WtVirtualFileSystem)?.refreshCachedPath(file.path)
                    }
                    WriteStatus.conflict -> throw IOException("Edit conflict: ${result.message ?: file.path}")
                    WriteStatus.error -> throw IOException("Save failed: ${result.message ?: file.path}")
                }
            }
        }
    }

    // The backend stamps journal writes itself; arbitrary timestamp/permission changes are unsupported.
    override fun setTimeStamp(file: VirtualFile, timeStamp: Long) = unsupported()
    override fun setWritable(file: VirtualFile, writableFlag: Boolean) = unsupported()
    override fun deleteFile(requestor: Any?, file: VirtualFile) = unsupported()
    override fun moveFile(requestor: Any?, file: VirtualFile, newParent: VirtualFile) = unsupported()
    override fun renameFile(requestor: Any?, file: VirtualFile, newName: String) = unsupported()
    override fun createChildFile(requestor: Any?, parent: VirtualFile, name: String): VirtualFile = unsupported()
    override fun createChildDirectory(requestor: Any?, parent: VirtualFile, name: String): VirtualFile = unsupported()
    override fun copyFile(requestor: Any?, file: VirtualFile, newParent: VirtualFile, name: String): VirtualFile = unsupported()
    private fun unsupported(): Nothing = throw IOException("Operation not supported by the managed wtbot prototype")
}
