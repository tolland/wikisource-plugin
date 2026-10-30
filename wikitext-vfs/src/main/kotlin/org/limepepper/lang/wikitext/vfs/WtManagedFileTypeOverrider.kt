package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.fileTypes.FileType
import com.intellij.openapi.fileTypes.impl.FileTypeOverrider
import com.intellij.openapi.vfs.VirtualFile

class WtManagedFileTypeOverrider : FileTypeOverrider {
    override fun getOverriddenFileType(file: VirtualFile): FileType? {
        val fs = file.fileSystem as? WtManagedBackendFileSystem ?: return null
        if (file.isDirectory) return null
        val metadata = fs.cachedMetadata(file) ?: return null
        return WtContentModel.fileTypeFor(metadata.contentModel)
    }
}
