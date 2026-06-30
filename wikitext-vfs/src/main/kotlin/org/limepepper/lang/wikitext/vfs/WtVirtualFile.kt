package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.fileTypes.FileType
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileSystem
import org.limepepper.lang.wikitext.WtFileType
import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.StatResult
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WriteStatus
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream

/**
 * Backend-backed [VirtualFile] for the `wikisource://` protocol.
 *
 * Content and children are lazy: the first call to [contentsToByteArray] or
 * [getChildren] hits the wtbot sidecar synchronously. Callers that need these
 * on a background thread (e.g. the tool window's TreeWillExpandListener) can
 * pre-populate [cachedChildren] / [cachedContent] before handing the instance
 * to Swing to avoid blocking the EDT.
 *
 * Instances are stable and cached by path in [WtVirtualFileSystem] —
 * callers should always obtain them via the filesystem, not construct directly.
 */
class WtVirtualFile(
    private val fileSystem: WtVirtualFileSystem,
    private val _name: String,
    private val _path: String,
    private val isDir: Boolean,
    private var _parent: WtVirtualFile? = null,
    val stableId: Long? = null,
    revid: Long? = null,
) : VirtualFile() {

    // Populated either eagerly by the tool window (BG thread) or lazily on
    // first access. Protected by `@Synchronized` on each accessor.
    @Volatile var cachedChildren: Array<VirtualFile>? = null
    @Volatile var cachedContent: ByteArray? = null

    // The revid this file's cached content is based on — the conflict token
    // sent back as base_revid on save. Updated on every successful write.
    @Volatile var revid: Long? = revid
        private set

    fun setParent(p: WtVirtualFile) { _parent = p }

    override fun getName(): String = _name
    override fun getFileSystem(): VirtualFileSystem = fileSystem
    override fun getPath(): String = _path
    override fun isWritable(): Boolean = !isDir
    override fun isDirectory(): Boolean = isDir
    override fun isValid(): Boolean = true
    override fun getParent(): VirtualFile? = _parent

    override fun getFileType(): FileType = if (isDir) super.getFileType() else WtFileType

    override fun getChildren(): Array<VirtualFile> {
        if (!isDir) return emptyArray()
        cachedChildren?.let { return it }
        // Blocking fetch — should be called off the EDT.
        val result = WtVfsService.instance.backend.listChildren(_path)
        @Suppress("UNCHECKED_CAST")
        val children = result.children.map { child ->
            fileSystem.getOrCreate(
                path = child.path,
                name = child.name,
                isDir = child.kind == NodeKind.directory,
                parent = this,
                stableId = child.stableId,
                revid = child.revid,
            )
        }.toTypedArray() as Array<VirtualFile>
        cachedChildren = children
        return children
    }

    override fun contentsToByteArray(): ByteArray {
        if (isDir) return ByteArray(0)
        val cached = cachedContent
        if (cached != null) return cached
        // Blocking fetch — IntelliJ calls this off the EDT via LoadTextUtil.
        val bytes = WtVfsService.instance.backend.readContent(_path).decodeContent()
        cachedContent = bytes
        return bytes
    }

    override fun getInputStream(): InputStream = ByteArrayInputStream(contentsToByteArray())

    override fun getOutputStream(requestor: Any?, newModificationStamp: Long, newTimeStamp: Long): OutputStream {
        if (isDir) throw IOException("cannot write a directory: $_path")
        return object : ByteArrayOutputStream() {
            // IntelliJ calls close() once on save, off the EDT, after the
            // editor has finished writing the new buffer into this stream.
            override fun close() {
                super.close()
                val bytes = toByteArray()
                val base64 = java.util.Base64.getEncoder().encodeToString(bytes)
                val result = try {
                    WtVfsService.instance.backend.writeContent(_path, base64, revid)
                } catch (e: VfsBackendException) {
                    throw IOException("save failed for $_path: ${e.message}", e)
                }
                when (result.status) {
                    WriteStatus.ok -> {
                        cachedContent = bytes
                        revid = result.newRevid
                    }
                    WriteStatus.conflict -> throw IOException(
                        "edit conflict saving $_path: ${result.message ?: "remote revision has changed"}"
                    )
                    WriteStatus.error -> throw IOException(
                        "save failed for $_path: ${result.message ?: "unknown error"}"
                    )
                }
            }
        }
    }

    override fun getLength(): Long = cachedContent?.size?.toLong() ?: 0L

    override fun getTimeStamp(): Long = 0L
    override fun getModificationStamp(): Long = 0L

    override fun refresh(asynchronous: Boolean, recursive: Boolean, postRunnable: Runnable?) {
        cachedChildren = null
        cachedContent = null
        postRunnable?.run()
    }

    companion object {
        const val PROTOCOL: String = WtVirtualFileSystem.PROTOCOL

        fun fromStat(fs: WtVirtualFileSystem, stat: StatResult): WtVirtualFile =
            WtVirtualFile(
                fileSystem = fs,
                _name = stat.path.substringAfterLast('/').ifEmpty { "/" },
                _path = stat.path,
                isDir = stat.kind == NodeKind.directory,
                stableId = stat.stableId,
                revid = stat.revid,
            )
    }
}
