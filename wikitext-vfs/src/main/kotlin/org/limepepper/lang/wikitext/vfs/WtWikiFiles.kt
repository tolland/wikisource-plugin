package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileManager

/** Boundary between backend resource paths and managed editor files. */
object WtWikiFiles {
    /** May contact wtbot; resolve off the EDT before opening an editor. */
    fun find(path: String): VirtualFile? =
        VirtualFileManager.getInstance().findFileByUrl(WtManagedAddress.fromPath(path).url)

    fun refreshAndFind(path: String): VirtualFile? =
        VirtualFileManager.getInstance().refreshAndFindFileByUrl(WtManagedAddress.fromPath(path).url)

    /** No I/O. Local files must not be mistaken for backend resources. */
    fun pathOf(file: VirtualFile?): String? =
        file?.takeIf { it.fileSystem is WtManagedBackendFileSystem }?.path

    fun contentModelOf(file: VirtualFile): String? =
        (file.fileSystem as? WtManagedBackendFileSystem)?.cachedMetadata(file)?.contentModel

    fun revisionOf(file: VirtualFile): Long? =
        (file.fileSystem as? WtManagedBackendFileSystem)?.cachedContentRevision(file)
}
