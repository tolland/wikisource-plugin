package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.util.io.FileAttributes
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.newvfs.NewVirtualFileSystem
import com.intellij.openapi.vfs.newvfs.RefreshQueue
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.OutputStream

/** In-memory data provider. ManagingFS owns the files, IDs, caches and events. */
class WtManagedDemoFileSystem : NewVirtualFileSystem() {
    private data class Body(val bytes: ByteArray, val timestamp: Long)

    @Volatile private var body = Body(
        "Managed Wikisource VFS experiment.\nOur aspirations include native Find and Replace.\n".toByteArray(),
        System.currentTimeMillis(),
    )

    override fun getProtocol(): String = PROTOCOL
    override fun isCaseSensitive(): Boolean = true
    override fun isReadOnly(): Boolean = false
    override fun extractRootPath(normalizedPath: String): String = if (normalizedPath.startsWith('/')) "/" else ""
    override fun findFileByPath(path: String): VirtualFile? = findFileByPath(this, path)
    override fun findFileByPathIfCached(path: String): VirtualFile? = findFileByPathIfCached(this, path)
    override fun refreshAndFindFileByPath(path: String): VirtualFile? {
        findFileByPathIfCached(path)?.refresh(false, false)
        return findFileByPath(path)
    }

    override fun refresh(asynchronous: Boolean) {
        val root = findFileByPathIfCached("/") ?: return
        RefreshQueue.getInstance().refresh(asynchronous, true, null, root)
    }

    override fun exists(file: VirtualFile): Boolean = file.path == "/" || file.path == FILE_PATH
    override fun isDirectory(file: VirtualFile): Boolean = file.path == "/"
    override fun list(file: VirtualFile): Array<String> = if (file.path == "/") arrayOf("probe.txt") else emptyArray()
    override fun isWritable(file: VirtualFile): Boolean = file.path == FILE_PATH
    override fun getTimeStamp(file: VirtualFile): Long = body.timestamp
    override fun getLength(file: VirtualFile): Long = if (file.path == FILE_PATH) body.bytes.size.toLong() else 0

    override fun getAttributes(file: VirtualFile): FileAttributes? {
        if (!exists(file)) return null
        val snapshot = body
        return FileAttributes(isDirectory(file), false, false, false,
            if (isDirectory(file)) 0 else snapshot.bytes.size.toLong(), snapshot.timestamp, isWritable(file))
    }

    override fun contentsToByteArray(file: VirtualFile): ByteArray {
        if (file.path != FILE_PATH) throw IOException("Not a demo content file: ${file.path}")
        return body.bytes.copyOf()
    }

    override fun getInputStream(file: VirtualFile) = ByteArrayInputStream(contentsToByteArray(file))

    override fun getOutputStream(file: VirtualFile, requestor: Any?, modStamp: Long, timeStamp: Long): OutputStream {
        if (file.path != FILE_PATH) throw IOException("Not a demo content file: ${file.path}")
        return object : ByteArrayOutputStream() {
            override fun close() {
                super.close()
                body = Body(toByteArray(), maxOf(System.currentTimeMillis(), body.timestamp + 1))
            }
        }
    }

    override fun setTimeStamp(file: VirtualFile, timeStamp: Long) { body = body.copy(timestamp = timeStamp) }
    override fun setWritable(file: VirtualFile, writableFlag: Boolean) = unsupported()
    override fun deleteFile(requestor: Any?, file: VirtualFile) = unsupported()
    override fun moveFile(requestor: Any?, file: VirtualFile, newParent: VirtualFile) = unsupported()
    override fun renameFile(requestor: Any?, file: VirtualFile, newName: String) = unsupported()
    override fun createChildFile(requestor: Any?, parent: VirtualFile, name: String): VirtualFile = unsupported()
    override fun createChildDirectory(requestor: Any?, parent: VirtualFile, name: String): VirtualFile = unsupported()
    override fun copyFile(requestor: Any?, file: VirtualFile, newParent: VirtualFile, name: String): VirtualFile = unsupported()

    private fun unsupported(): Nothing = throw IOException("The managed VFS demo has a fixed layout")

    companion object {
        const val PROTOCOL = "wikisource-demo"
        const val FILE_PATH = "/probe.txt"
        const val URL = "$PROTOCOL://$FILE_PATH"
    }
}
