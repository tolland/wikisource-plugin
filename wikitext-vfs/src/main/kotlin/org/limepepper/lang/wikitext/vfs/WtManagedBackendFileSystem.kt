package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.util.io.FileAttributes
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileWithId
import com.intellij.openapi.vfs.newvfs.FileAttribute
import com.intellij.openapi.vfs.newvfs.NewVirtualFile
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.vfs.newvfs.NewVirtualFileSystem
import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.StatResult
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WriteStatus
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.EOFException
import java.io.OutputStream
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap

/** Managed file objects backed by wtbot; legacy URL lookups resolve to these same identities. */

class WtManagedBackendFileSystem : NewVirtualFileSystem() {
    private data class ContentSnapshot(val connection: String, val revision: Long?, val model: String?, val databaseId: String?)
    private fun snapshot(file: VirtualFile): ContentSnapshot? {
        if (file !is VirtualFileWithId || file.id <= 0) return null
        return CONTENT_SNAPSHOT.readFileAttribute(file)?.use { input ->
            val connection = input.readUTF()
            val model = input.readUTF().ifEmpty { null }
            val revision = if (input.readBoolean()) input.readLong() else null
            val databaseId = try { input.readUTF().ifEmpty { null } } catch (_: EOFException) { null }
            ContentSnapshot(connection, revision, model, databaseId)
        }?.takeIf { it.connection == backend.cacheIdentity }
    }

    private fun rememberContent(file: VirtualFile, current: VfsBackend, revision: Long?, databaseId: String?) {
        val identity = current.cacheIdentity ?: return
        if (file !is VirtualFileWithId || file.id <= 0) return
        val model = cachedMetadata(file)?.contentModel
        CONTENT_SNAPSHOT.writeFileAttribute(file).use { output ->
            output.writeUTF(identity)
            output.writeUTF(model.orEmpty())
            output.writeBoolean(revision != null)
            if (revision != null) output.writeLong(revision)
            output.writeUTF(databaseId.orEmpty())
        }
    }
    private data class ReadVersion(val backend: VfsBackend, val revid: Long?, val databaseId: String? = null)
    private val readVersions = ConcurrentHashMap<String, ReadVersion>()
    private val diskVersions = ConcurrentHashMap<String, ReadVersion>()
    private val failedWrites = ConcurrentHashMap.newKeySet<String>()
    private val metadata = ConcurrentHashMap<String, StatResult>()
    private val invalidatedDatabases = ConcurrentHashMap<String, String>()
    private val connectionChanges = ConcurrentHashMap.newKeySet<String>()
    private val backend: VfsBackend get() = WtVfsService.instance.backend

    override fun getProtocol(): String = WtManagedAddress.PROTOCOL
    override fun isCaseSensitive(): Boolean = true
    override fun isReadOnly(): Boolean = false
    override fun extractRootPath(normalizedPath: String): String = address(normalizedPath).rootPath
    override fun findFileByPath(path: String): VirtualFile? = try {
        findFileByPath(this, address(path).backendPath)?.also {
            // An explicit lookup must revalidate the database binding, even if
            // a file's ordinary metadata and persistent record are unchanged.
            val state = stat(it)
            // Managed flags survive IDE restarts. Correct earlier read-only
            // records via VFS events, which also update cached Documents.
            if (state.exists && (it.isWritable != state.writable ||
                it.timeStamp != (state.timestamp?.toLongOrNull() ?: 0) ||
                (!it.isDirectory && it.length != (state.length ?: 0)) || databaseChanged(it, state))) refreshFile(it)
        }
    } catch (_: VfsBackendException) {
        // A refused connection is not evidence that a known resource was deleted.
        findFileByPathIfCached(path)
    }
    @Suppress("JetBrainsInternalApiUsage")
    override fun findFileByPathIfCached(path: String): VirtualFile? = findFileByPathIfCached(this, address(path).backendPath)
    override fun refreshAndFindFileByPath(path: String): VirtualFile? {
        // Refresh a known ancestor as well: the requested child may be newly created.
        var ancestor = address(path).backendPath
        while (true) {
            val cached = findFileByPathIfCached(ancestor)
            if (cached != null) {
                refreshFile(cached, false)
                break
            }
            if (ancestor == "/") break
            ancestor = ancestor.substringBeforeLast('/').ifEmpty { "/" }
        }
        return findFileByPath(path)
    }

    override fun refresh(asynchronous: Boolean) {
        if (asynchronous) {
            ApplicationManager.getApplication().executeOnPooledThread { refresh(false) }
            return
        }
        try { backend.stat("/") }
        catch (_: VfsBackendException) { return }
        val roots = com.intellij.openapi.vfs.newvfs.ManagingFS.getInstance().getRoots(this)
        // The API's directory listings are relationship views (e.g. hidden Page
        // namespaces and @pages edges). Never use them to recursively reconcile
        // the physical mount. Refresh only leaves already known to persistent VFS.
        val pending = java.util.ArrayDeque<VirtualFile>(roots.toList())
        while (pending.isNotEmpty()) {
            val file = pending.removeFirst()
            if (!file.isValid) continue
            if (file.isDirectory) pending.addAll((file as NewVirtualFile).iterInDbChildren().toList())
            else try { refreshFile(file, false) } catch (_: VfsBackendException) { return }
        }
    }

    fun refreshFile(file: VirtualFile, asynchronous: Boolean = true) {
        require(file.fileSystem === this)
        if (asynchronous) {
            ApplicationManager.getApplication().executeOnPooledThread {
                try { refreshFile(file, false) }
                catch (failure: VfsBackendException) { LOG.warn("Managed refresh unavailable for ${file.path}", failure) }
            }
            return
        }
        if (!file.isValid) return
        // Fail before entering the platform refresh worker, where transport
        // exceptions otherwise become IDE errors. Keep cached files intact.
        val state = stat(file)
        if (state.exists && databaseChanged(file, state)) {
            ApplicationManager.getApplication().invokeAndWait {
                ApplicationManager.getApplication().runWriteAction {
                    if (file.isValid) {
                        WtManagedSaveRecovery.invalidate(file)
                        val documents = FileDocumentManager.getInstance()
                        val document = documents.getCachedDocument(file)
                        if (document != null && !documents.isDocumentUnsaved(document)) documents.reloadFromDisk(document)
                        if (document == null || documents.isDocumentUnsaved(document) || readVersions[file.path]?.databaseId == state.databaseId) {
                            invalidatedDatabases[file.path] = requireNotNull(state.databaseId)
                            connectionChanges.remove(file.path)
                        }
                    }
                }
            }
        }
        (file as NewVirtualFile).markDirty()
        file.refresh(asynchronous, false)
    }

    private fun address(path: String) = WtManagedAddress.fromPath(path)
    fun resetConnection(file: VirtualFile) {
        connectionChanges.add(file.path)
        metadata.remove(file.path)
        invalidatedDatabases.remove(file.path)
        readVersions.remove(file.path)
        diskVersions.remove(file.path)
    }

    internal fun hasFailedWrite(file: VirtualFile) = file.path in failedWrites

    private fun sameConnection(current: VfsBackend, version: ReadVersion) =
        version.backend === current || (current.requiresDatabaseIdentity && version.databaseId != null &&
            current.cacheIdentity == version.backend.cacheIdentity)
    private fun databaseChanged(file: VirtualFile, state: StatResult): Boolean {
        val databaseId = state.databaseId ?: return false
        if (file.path in connectionChanges) return true
        if (file.isDirectory || invalidatedDatabases[file.path] == databaseId) return false
        val version = readVersions[file.path]
        val recorded = snapshot(file)
        if (version == null && recorded == null) return false
        val previous = version?.databaseId ?: recorded?.databaseId
        return previous != databaseId
    }
    private fun stat(file: VirtualFile): StatResult {
        val resource = address(file.path)
        val result = if (resource.backendPath == "/") {
            // The logical mount must exist before ManagingFS can rehydrate
            // persisted children, even when no service is reachable.
            StatResult("/", true, "/", NodeKind.directory)
        } else if (resource.isFamilyContainer) {
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

    /** No backend requests: file-type selection can happen on the EDT. */
    fun cachedMetadata(file: VirtualFile): StatResult? = metadata[file.path] ?: snapshot(file)?.let {
        StatResult(path = file.path, exists = true, contentModel = it.model,
            revid = it.revision, writable = file.isWritable, databaseId = it.databaseId)
    }

    /** Revision of the content read by the editor, rather than a later metadata refresh. */
    fun cachedContentRevision(file: VirtualFile): Long? {
        val version = readVersions[file.path]
        return if (version != null) version.revid else snapshot(file)?.revision ?: metadata[file.path]?.revid
    }

    override fun exists(file: VirtualFile): Boolean = stat(file).exists
    override fun isDirectory(file: VirtualFile): Boolean = stat(file).kind == NodeKind.directory
    override fun isWritable(file: VirtualFile): Boolean = stat(file).writable
    override fun getTimeStamp(file: VirtualFile): Long = stat(file).timestamp?.toLongOrNull() ?: 0
    override fun getLength(file: VirtualFile): Long = stat(file).length ?: 0
    override fun getAttributes(file: VirtualFile): FileAttributes? {
        val state = try { stat(file) }
        catch (failure: VfsBackendException) {
            // Native refresh also calls this without going through refreshFile.
            // Preserve known records on transport failure; only exists=false
            // from a successful stat is evidence for a deletion event.
            val cached = (file as? NewVirtualFile)?.takeIf { it.isValid }
                ?: findFileByPathIfCached(file.path) ?: throw failure
            return FileAttributes(cached.isDirectory, false, false, false,
                cached.length, cached.timeStamp, cached.isWritable)
        }
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
        val listing = backend.listChildren(path)
        return listing.children.map { child ->
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
                hasChildren = child.hasChildren, aspects = child.aspects, databaseId = listing.databaseId)
            name
        }.toTypedArray()
    }

    override fun contentsToByteArray(file: VirtualFile): ByteArray {
        val current = backend
        val content = current.readContent(address(file.path).backendPath)
        diskVersions[file.path] = ReadVersion(current, content.revid, content.databaseId)
        // Refresh/diff may read newer disk bytes while the editor keeps unsaved
        // text. Those reads must not advance that Document's save conflict token.
        val documents = FileDocumentManager.getInstance()
        val document = documents.getCachedDocument(file)
        if (file.path !in failedWrites && (document == null || !documents.isDocumentUnsaved(document))) {
            readVersions[file.path] = ReadVersion(current, content.revid, content.databaseId)
            rememberContent(file, current, content.revid, content.databaseId)
        }
        return content.decodeContent()
    }

    internal fun contentReloaded(file: VirtualFile) {
        val version = diskVersions[file.path] ?: return
        if (version.backend !== backend) return
        readVersions[file.path] = version
        failedWrites.remove(file.path)
        rememberContent(file, version.backend, version.revid, version.databaseId)
    }

    override fun getInputStream(file: VirtualFile) = ByteArrayInputStream(contentsToByteArray(file))

    override fun getOutputStream(file: VirtualFile, requestor: Any?, modStamp: Long, timeStamp: Long): OutputStream =
        try { outputStream(file) }
        catch (failure: IOException) {
            failedWrites.add(file.path)
            WtManagedSaveRecovery.failed(file)
            throw failure
        }

    private fun outputStream(file: VirtualFile): OutputStream {
        val current = backend
        val version = readVersions[file.path]
            ?: snapshot(file)?.let { ReadVersion(current, it.revision, it.databaseId) }
            ?: throw IOException("Content revision is unknown; reload before saving ${file.path}")
        if (!sameConnection(current, version)) throw IOException("Backend changed since this file was read; reload before saving")
        if (current.requiresDatabaseIdentity && version.databaseId == null) throw IOException("Database identity is unknown; reload before saving")
        return object : ByteArrayOutputStream() {
            override fun close() {
                super.close()
                try {
                    if (backend !== current) throw IOException("Backend changed before save; reload before saving")
                    val result = current.writeContent(address(file.path).backendPath,
                        Base64.getEncoder().encodeToString(toByteArray()), version.revid, databaseId = version.databaseId)
                    when (result.status) {
                        WriteStatus.ok -> {
                            readVersions[file.path] = ReadVersion(current, result.newRevid, result.databaseId)
                            failedWrites.remove(file.path)
                            diskVersions[file.path] = ReadVersion(current, result.newRevid, result.databaseId)
                            rememberContent(file, current, result.newRevid, result.databaseId)
                            metadata.computeIfPresent(file.path) { _, previous ->
                                previous.copy(revid = result.newRevid, length = size().toLong(), dirty = true,
                                    timestamp = System.currentTimeMillis().toString())
                            }
                        }
                        WriteStatus.conflict -> throw IOException("Edit conflict: ${result.message ?: file.path}")
                        WriteStatus.error -> throw IOException("Save failed: ${result.message ?: file.path}")
                    }
                } catch (failure: IOException) {
                    failedWrites.add(file.path)
                    WtManagedSaveRecovery.failed(file)
                    throw failure
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

    companion object {
        private val LOG = Logger.getInstance(WtManagedBackendFileSystem::class.java)
        private val CONTENT_SNAPSHOT = FileAttribute("wikisource.wtbot.content", 1, false)
    }
}
