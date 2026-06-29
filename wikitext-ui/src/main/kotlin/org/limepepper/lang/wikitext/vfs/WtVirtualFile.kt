package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileSystem
import java.io.ByteArrayInputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream

/**
 * Minimal in-memory [VirtualFile] for the first wiring milestone. Holds its
 * own name, content, children, and parent directly -- no SQLite, no fetch.
 *
 * This is deliberately hand-rolled rather than using the platform's
 * LightVirtualFile because LightVirtualFile is flat (no children) and the
 * whole point of this slice is proving the Index -> Page *hierarchy* renders
 * in a tree. Once SQLite backing is real, the content/children accessors here
 * become DB reads; the shape stays the same.
 *
 * Everything is read-only and writable=false for now.
 */
class WtVirtualFile(
    private val fileSystem: WtVirtualFileSystem,
    private val name: String,
    private val path: String,
    private val isDir: Boolean,
    private val content: ByteArray = ByteArray(0),
    private var parent: WtVirtualFile? = null,
    private val childList: MutableList<WtVirtualFile> = mutableListOf(),
) : VirtualFile() {

    init {
        childList.forEach { it.parent = this }
    }

    fun addChild(child: WtVirtualFile): WtVirtualFile {
        child.parent = this
        childList.add(child)
        return child
    }

    override fun getName(): String = name

    override fun getFileSystem(): VirtualFileSystem = fileSystem

    override fun getPath(): String = path

    override fun isWritable(): Boolean = false

    override fun isDirectory(): Boolean = isDir

    override fun isValid(): Boolean = true

    override fun getParent(): VirtualFile? = parent

    override fun getChildren(): Array<VirtualFile> = childList.toTypedArray()

    override fun contentsToByteArray(): ByteArray = content

    override fun getInputStream(): InputStream = ByteArrayInputStream(content)

    override fun getOutputStream(requestor: Any?, newModificationStamp: Long, newTimeStamp: Long): OutputStream {
        // Read-only for this milestone. Real impl: write through to SQLite.
        throw IOException("$PROTOCOL files are read-only in this milestone")
    }

    override fun getLength(): Long = content.size.toLong()

    override fun getTimeStamp(): Long = 0L

    override fun getModificationStamp(): Long = 0L

    override fun refresh(asynchronous: Boolean, recursive: Boolean, postRunnable: Runnable?) {
        // No-op for in-memory dummy. Real impl: re-read row from SQLite, fire
        // events if local_modified_at moved.
        postRunnable?.run()
    }

    companion object {
        const val PROTOCOL: String = WtVirtualFileSystem.PROTOCOL
    }
}
