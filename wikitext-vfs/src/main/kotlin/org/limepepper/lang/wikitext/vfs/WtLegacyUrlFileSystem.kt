package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileSystem
import com.intellij.openapi.vfs.VirtualFileListener
import java.io.IOException

/** Compatibility lookup only. Graph nodes and editor content have separate owners. */
class WtLegacyUrlFileSystem : VirtualFileSystem() {
    override fun getProtocol() = WtVirtualFileSystem.PROTOCOL
    override fun findFileByPath(path: String): VirtualFile? = WtWikiFiles.find(path)
    override fun refreshAndFindFileByPath(path: String): VirtualFile? = WtWikiFiles.refreshAndFind(path)
    // This alias owns no records. Returned files refresh through their managed filesystem.
    override fun refresh(asynchronous: Boolean) {}
    override fun addVirtualFileListener(listener: VirtualFileListener) {}
    override fun removeVirtualFileListener(listener: VirtualFileListener) {}

    override fun deleteFile(requestor: Any?, vFile: VirtualFile) { throw IOException("delete not supported") }
    override fun moveFile(requestor: Any?, vFile: VirtualFile, newParent: VirtualFile) { throw IOException("move not supported") }
    override fun renameFile(requestor: Any?, vFile: VirtualFile, newName: String) { throw IOException("rename not supported") }
    override fun createChildFile(requestor: Any?, vDir: VirtualFile, fileName: String): VirtualFile { throw IOException("createChildFile not supported") }
    override fun createChildDirectory(requestor: Any?, vDir: VirtualFile, dirName: String): VirtualFile { throw IOException("createChildDirectory not supported") }
    override fun copyFile(requestor: Any?, virtualFile: VirtualFile, newParent: VirtualFile, copyName: String): VirtualFile { throw IOException("copyFile not supported") }

    override fun isReadOnly() = true
    override fun isCaseSensitive() = true
}
