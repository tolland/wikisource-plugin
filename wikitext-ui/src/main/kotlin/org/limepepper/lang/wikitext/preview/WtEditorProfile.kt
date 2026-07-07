package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.vfs.VirtualFile
import org.limepepper.lang.wikitext.preview.WtEditorProfile.Companion.forFile
import org.limepepper.lang.wikitext.vfs.WtContentModel
import org.limepepper.lang.wikitext.vfs.WtVirtualFile

/**
 * What the split editor offers for a given MediaWiki content model. The
 * provider picks the profile once per file (see [forFile]) and it drives both
 * which [WtEditorWithPreview] subclass is built and which toolbar actions the
 * preview pane shows.
 *
 * Capabilities so far are stubs of the real per-model behavior:
 *  - [PROOFREAD_PAGE] pages have a reference scan and a body convention of
 *    `<noinclude>header</noinclude>body<noinclude>footer</noinclude>` that
 *    must survive editing round trips.
 *  - [PROOFREAD_INDEX] pages have no scan of their own; the wiki renders
 *    their body through `{{:MediaWiki:Proofreadpage_index_template}}` (the
 *    preview already shows that server-side rendering, since the sidecar
 *    passes the content model to `action=parse`).
 *  - [WIKITEXT] is the unrestricted fallback for plain wikitext and any
 *    content model we don't know.
 */
enum class WtEditorProfile(
    val hasReferenceImage: Boolean,
    val hasPageNavigation: Boolean,
) {
    PROOFREAD_PAGE(hasReferenceImage = true, hasPageNavigation = true),
    PROOFREAD_INDEX(hasReferenceImage = false, hasPageNavigation = false),
    WIKITEXT(hasReferenceImage = false, hasPageNavigation = false),
    ;

    companion object {
        /**
         * Local scratch files carry no content model and fall back to
         * [WIKITEXT], as does any model this plugin doesn't recognize.
         */
        fun forFile(file: VirtualFile): WtEditorProfile =
            when ((file as? WtVirtualFile)?.contentModel) {
                WtContentModel.PROOFREAD_PAGE.wikiId -> PROOFREAD_PAGE
                WtContentModel.PROOFREAD_INDEX.wikiId -> PROOFREAD_INDEX
                else -> WIKITEXT
            }
    }
}
