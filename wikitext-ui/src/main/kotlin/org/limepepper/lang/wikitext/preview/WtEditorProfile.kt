package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.vfs.VirtualFile
import org.limepepper.lang.wikitext.preview.WtEditorProfile.Companion.forFile
import org.limepepper.lang.wikitext.vfs.WtContentModel
import org.limepepper.lang.wikitext.vfs.WtVirtualFile

/**
 * What the split editor offers for a given MediaWiki content model. The
 * provider picks the profile once per file (see [forFile]) and it drives
 * which [WtEditorWithPreview] subclass is built.
 *
 *  - [PROOFREAD_INDEX] pages have no scan of their own; the wiki renders
 *    their body through `{{:MediaWiki:Proofreadpage_index_template}}` (the
 *    preview already shows that server-side rendering, since the sidecar
 *    passes the content model to `action=parse`).
 *  - [WIKITEXT] is the unrestricted fallback for plain wikitext and any
 *    content model we don't know.
 *
 * `proofread-page` content is not a profile here: those files carry
 * [org.limepepper.lang.wikitext.PrpFileType] and open in the dedicated
 * [org.limepepper.lang.wikitext.editor.prp.PrpFileEditorProvider].
 */
enum class WtEditorProfile {
    PROOFREAD_INDEX,
    WIKITEXT,
    ;

    companion object {
        /**
         * Local scratch files carry no content model and fall back to
         * [WIKITEXT], as does any model this plugin doesn't recognize.
         */
        fun forFile(file: VirtualFile): WtEditorProfile =
            when ((file as? WtVirtualFile)?.contentModel) {
                WtContentModel.PROOFREAD_INDEX.wikiId -> PROOFREAD_INDEX
                else -> WIKITEXT
            }
    }
}
