package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.fileTypes.FileType
import com.intellij.openapi.fileTypes.FileTypeRegistry
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileSystem
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
    /**
     * Remote contentmodel (e.g. "proofread-index", "proofread-page", "wikitext",
     * "sanitized-css", "json") — drives [getFileType] via [WtContentModel].
     */
    val contentModel: String? = null,
    qualityLevel: Int? = null,
    dirty: Boolean = false,
    hasReferenceImage: Boolean = false,
    placeholder: Boolean = false,
    length: Long? = null,
    timestamp: String? = null,
) : VirtualFile() {

    // Populated either eagerly by the tool window (BG thread) or lazily on
    // first access. Protected by `@Synchronized` on each accessor.
    @Volatile var cachedChildren: Array<VirtualFile>? = null
    @Volatile var cachedContent: ByteArray? = null

    // Backend-reported facts about the effective body — the same content a
    // read of this path serves (server precedence: uncommitted journal >
    // pushed-not-yet-refetched commit > remote snapshot > placeholder
    // default). Length is superseded by cachedContent once loaded;
    // timestamp is epoch millis of the page's last local save or remote
    // revision, whichever backs the current body.
    @Volatile private var statLength: Long? = length
    @Volatile private var statTimestamp: Long? = timestamp?.toLongOrNull()

    // The revid this file's cached content is based on — the conflict token
    // sent back as base_revid on save. Updated on every successful write.
    @Volatile var revid: Long? = revid
        private set

    // Decoration metadata, refreshed on every backend sighting of this path
    // (stat, children listing). Drives tree colour-coding in the tool window.
    /** ProofreadPage quality 0-4; null for non-proofread files and dirs. */
    @Volatile var qualityLevel: Int? = qualityLevel
        private set
    /** Uncommitted local edits (EditJournal) exist for the backing page. */
    @Volatile var dirty: Boolean = dirty
        private set
    /** A scan reference image is known; pixels via GET /reference-image. */
    @Volatile var hasReferenceImage: Boolean = hasReferenceImage
        private set
    /** No remote revision backs this file — a missing proofread page's
     * local stub. Opening it starts a new transcription. */
    @Volatile var placeholder: Boolean = placeholder
        private set

    fun setParent(p: WtVirtualFile) { _parent = p }

    /** Refresh decoration metadata from a fresh backend sighting. Length and
     * timestamp are only overwritten when the sighting carries them (stats
     * and file listings do; directory rows don't). */
    fun updateMeta(
        qualityLevel: Int?,
        dirty: Boolean,
        hasReferenceImage: Boolean,
        placeholder: Boolean,
        length: Long? = null,
        timestamp: String? = null,
    ) {
        this.qualityLevel = qualityLevel
        this.dirty = dirty
        this.hasReferenceImage = hasReferenceImage
        this.placeholder = placeholder
        length?.let { statLength = it }
        timestamp?.toLongOrNull()?.let { statTimestamp = it }
    }

    /**
     * Called by [WtVirtualFileSystem.refresh] with a freshly fetched stat.
     * Content is re-fetched lazily on next access when the revid has moved on;
     * children are always invalidated since listings carry no revid of their own.
     */
    @Synchronized
    fun invalidateIfStale(stat: StatResult) {
        updateMeta(
            stat.qualityLevel, stat.dirty, stat.hasReferenceImage, stat.placeholder,
            stat.length, stat.timestamp,
        )
        if (stat.revid != revid) {
            revid = stat.revid
            cachedContent = null
        }
        cachedChildren = null
    }

    override fun getName(): String = _name
    override fun getFileSystem(): VirtualFileSystem = fileSystem
    override fun getPath(): String = _path
    override fun isWritable(): Boolean = !isDir
    override fun isDirectory(): Boolean = isDir
    override fun isValid(): Boolean = true
    override fun getParent(): VirtualFile? = _parent

    fun getFileTypeForFile() {
        FileTypeRegistry.getInstance().getFileTypeByFileName("dummy.css")
    }

    override fun getFileType(): FileType =
        if (isDir) super.getFileType() else WtContentModel.fileTypeFor(contentModel)

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
                contentModel = child.contentModel,
                qualityLevel = child.qualityLevel,
                dirty = child.dirty,
                hasReferenceImage = child.hasReferenceImage,
                placeholder = child.placeholder,
                length = child.length,
                timestamp = child.timestamp,
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
                        statLength = bytes.size.toLong()
                        // The backend stamps local_modified_at at save time;
                        // mirror it locally so length/stamps move with the
                        // content without waiting for the next re-stat.
                        statTimestamp = System.currentTimeMillis()
                        revid = result.newRevid
                        // A local save is journalled, not pushed — the page is
                        // now dirty relative to the wiki until committed.
                        dirty = true
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

    override fun getLength(): Long = cachedContent?.size?.toLong() ?: statLength ?: 0L

    /** Last modification of the effective body (local save or remote
     * revision), epoch millis as reported by the backend stat. */
    override fun getTimeStamp(): Long = statTimestamp ?: 0L

    // The platform compares modification stamps for staleness, not order, so
    // the backend timestamp doubles as the stamp: it moves exactly when the
    // effective body does (save, remote revision, post-commit refetch).
    override fun getModificationStamp(): Long = statTimestamp ?: 0L

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
                _name = stat.name ?: stat.path.substringAfterLast('/').ifEmpty { "/" },
                _path = stat.path,
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
            )
    }
}
