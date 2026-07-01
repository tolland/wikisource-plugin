package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.fileTypes.FileType
import com.intellij.openapi.fileTypes.PlainTextFileType
import org.limepepper.lang.wikitext.WtFileType

/**
 * MediaWiki contentmodel identifiers this plugin knows about, and the
 * IntelliJ [FileType] each should open as.
 *
 * This classifies [org.limepepper.lang.wikitext.vfs.backend.StatResult.contentModel] —
 * the single textual content model `stat()`/`list_children()` report per
 * VFS node today. It is distinct from MediaWiki's per-*slot* `contentformat`
 * (a fetched Revision carries a `slots` map, e.g. `slots.main.contentformat`;
 * multi-content revisions can have more than one slot). The VFS doesn't
 * expose multiple slots per node yet. When File:/transcluded-file support
 * lands and a node can carry non-text slot content (an image blob alongside
 * its wikitext description, say), that's the place to grow a slot-keyed
 * mapping rather than overloading this one.
 */
enum class WtContentModel(val wikiId: String, val fileType: FileType) {
    PROOFREAD_INDEX("proofread-index", WtFileType),
    PROOFREAD_PAGE("proofread-page", WtFileType),
    WIKITEXT("wikitext", WtFileType),

    // Not wikitext syntax — parsing these with the Wikitext lexer would just
    // produce garbage annotations. Plain text until this plugin has real
    // CSS/JSON PSI support (tracked alongside the File:/transclusion work).
    SANITIZED_CSS("sanitized-css", PlainTextFileType.INSTANCE),
    JSON("json", PlainTextFileType.INSTANCE),
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
