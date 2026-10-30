package org.limepepper.lang.wikitext.search

import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileManager
import com.intellij.openapi.vfs.VirtualFileWithId
import com.intellij.util.indexing.IndexableSetContributor

/** An intentionally bounded experiment: never return the database's directory root. */
class WtStaticIndexableSetContributor : IndexableSetContributor() {
    override fun getAdditionalRootsToIndex(): Set<VirtualFile> = emptySet()

    override fun getAdditionalProjectRootsToIndex(project: Project): Set<VirtualFile> =
        WtStaticSearchFiles.resolve().also { files ->
            val log = Logger.getInstance(WtStaticIndexableSetContributor::class.java)
            if (files.isEmpty()) log.info("Wikisource indexing demo: static page unavailable")
            files.forEach { file ->
                log.info(
                    "Wikisource indexing demo: ${file.url}, implementation=${file.javaClass.name}, " +
                        "persistentId=${(file as? VirtualFileWithId)?.id ?: "none"}"
                )
            }
        }
}

/** Shared by the indexing contributor and the explicit Find/Replace scope. */
object WtStaticSearchFiles {
    const val URL = "wikisource:///mywikisource/en/Page/Stevenson-Persuasive Definitions-1938.pdf/13/@wikitext"

    fun resolve(): Set<VirtualFile> {
        return setOfNotNull(
            VirtualFileManager.getInstance().findFileByUrl(URL)?.takeIf { it.isValid }
        )
    }
}
