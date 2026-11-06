package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.fileTypes.FileType
import com.intellij.openapi.fileTypes.FileTypeRegistry
import org.limepepper.lang.wikitext.WtFileType
import org.limepepper.lang.wikitext.PrpFileType

/**
 * MediaWiki contentmodel identifiers this plugin knows about, and the
 * IntelliJ [FileType] each should open as.
 */
enum class WtContentModel(val wikiId: String, val fileType: FileType) {
    PROOFREAD_INDEX("proofread-index", WtFileType),
    PROOFREAD_PAGE("proofread-page", PrpFileType),
    WIKITEXT("wikitext", WtFileType),
    SANITIZED_CSS("sanitized-css", FileTypeRegistry.getInstance().getFileTypeByFileName("dummy.css")),
    JSON("json", FileTypeRegistry.getInstance().getFileTypeByFileName("dummy.json")),
    ;

    companion object {
        private val byWikiId = entries.associateBy { it.wikiId }

        /**
         * [contentModel] is null for directories, legacy/untagged nodes, and
         * any MediaWiki contentmodel this enum doesn't list yet — all
         * conservatively default to [WtFileType], the plugin's original
         * always-wikitext behavior, rather than guessing.
         */
        fun fileTypeFor(contentModel: String?): FileType =
            contentModel?.let { byWikiId[it]?.fileType } ?: WtFileType
    }
}
