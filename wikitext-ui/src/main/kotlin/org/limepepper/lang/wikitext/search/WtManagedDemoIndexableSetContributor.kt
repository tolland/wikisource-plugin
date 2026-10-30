package org.limepepper.lang.wikitext.search

import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileManager
import com.intellij.openapi.vfs.VirtualFileWithId
import com.intellij.openapi.vfs.newvfs.ManagingFS
import com.intellij.util.indexing.IndexableSetContributor
import org.limepepper.lang.wikitext.vfs.WtManagedDemoFileSystem

class WtManagedDemoIndexableSetContributor : IndexableSetContributor() {
    override fun getAdditionalRootsToIndex(): Set<VirtualFile> = emptySet()

    override fun getAdditionalProjectRootsToIndex(project: Project): Set<VirtualFile> =
        managedDemoFiles().also { files ->
            files.forEach { file ->
                val id = (file as VirtualFileWithId).id
                Logger.getInstance(javaClass).info(
                    "Managed VFS demo: ${file.url}, id=$id, " +
                        "roundTrip=${ManagingFS.getInstance().findFileById(id) == file}"
                )
            }
        }
}

fun managedDemoFiles(): Set<VirtualFile> = setOfNotNull(
    VirtualFileManager.getInstance().findFileByUrl(WtManagedDemoFileSystem.URL)
)
