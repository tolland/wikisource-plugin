package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileListener
import com.intellij.openapi.vfs.VirtualFileSystem
import java.io.IOException
import java.nio.file.Path

/**
 * Milestone version: serves a single hardcoded in-memory tree so the tool
 * window has something to render and open. No SQLite, no network.
 *
 * Protocol/path shape (as eventually intended):
 *   wikisource://<site-host>/<namespaced-title>
 * For the dummy tree we use a flat synthetic path under one fake site.
 *
 * Registered application-level via `com.intellij.virtualFileSystem`; the EP
 * `key` must equal [PROTOCOL]. NOTE: needs sqlite-jdbc once real (currently
 * declared in :wikitext-ui) -- move or re-declare if this lands in core.
 */
class WtVirtualFileSystem : VirtualFileSystem() {

    companion object {
        const val PROTOCOL: String = "wikisource"

    }

    /** Hardcoded dummy tree: one Index with a few Page children. */
    val dummyRoot: WtVirtualFile by lazy { buildDummyTree() }

    private fun buildDummyTree(): WtVirtualFile {
        val indexName = "Index:The principles of mechanics (Hertz, 1894).pdf"
        val index = WtVirtualFile(
            fileSystem = this,
            name = indexName,
            path = "/$indexName",
            isDir = true,
        )
        for (n in listOf(1, 2, 3, 171, 172)) {
            index.addChild(
                WtVirtualFile(
                    fileSystem = this,
                    name = "Page $n",
                    path = "/$indexName/$n",
                    isDir = false,
                    content = "== Dummy page $n ==\n\nSome '''wikitext''' for page $n.\n".toByteArray(),
                )
            )
        }
        return index
    }

    override fun getProtocol(): String = PROTOCOL

    override fun findFileByPath(path: String): VirtualFile? {
        if (path == dummyRoot.path) return dummyRoot
        return dummyRoot.children.firstOrNull { it.path == path }
    }

    override fun refresh(asynchronous: Boolean) {}

    override fun refreshAndFindFileByPath(path: String): VirtualFile? = findFileByPath(path)

    override fun addVirtualFileListener(listener: VirtualFileListener) {}

    override fun removeVirtualFileListener(listener: VirtualFileListener) {}

    override fun deleteFile(requestor: Any?, vFile: VirtualFile) {
        throw IOException("delete not supported yet")
    }

    override fun moveFile(requestor: Any?, vFile: VirtualFile, newParent: VirtualFile) {
        throw IOException("move not supported yet")
    }

    override fun renameFile(requestor: Any?, vFile: VirtualFile, newName: String) {
        throw IOException("rename not supported yet")
    }

    override fun createChildFile(requestor: Any?, vDir: VirtualFile, fileName: String): VirtualFile {
        throw IOException("createChildFile not supported yet")
    }

    override fun createChildDirectory(requestor: Any?, vDir: VirtualFile, dirName: String): VirtualFile {
        throw IOException("createChildDirectory not supported yet")
    }

    override fun copyFile(
        requestor: Any?,
        virtualFile: VirtualFile,
        newParent: VirtualFile,
        copyName: String,
    ): VirtualFile {
        throw IOException("copyFile not supported yet")
    }

    override fun isReadOnly(): Boolean = true

    override fun isCaseSensitive(): Boolean = true

    override fun isValidName(name: String): Boolean = name.isNotEmpty()

    override fun getNioPath(file: VirtualFile): Path? = null
}

// Convenience access for the tool window in this milestone. Real code
// resolves via VirtualFileManager.getInstance().getFileSystem(PROTOCOL).
val INSTANCE: WtVirtualFileSystem by lazy { WtVirtualFileSystem() }
