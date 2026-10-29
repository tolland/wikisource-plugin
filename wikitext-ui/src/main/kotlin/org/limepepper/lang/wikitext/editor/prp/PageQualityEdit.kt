package org.limepepper.lang.wikitext.editor.prp

/**
 * Rewrites the `<pagequality level="…" />` tag of a serialized proofread-page.
 * Only the level changes: `user=` is left as is, since ProofreadPage sets it
 * server-side when a page is saved at level 3 or 4.
 */
object PageQualityEdit {

    /**
     * [text] with its quality level set to [level], or `null` when it can't be
     * done losslessly -- not a recognisable proofread-page (empty, unbalanced
     * `<noinclude>`, V1 layout). Returns [text] unchanged when the level
     * already matches. A page with no tag gets one with an empty user.
     */
    fun withLevel(text: String, level: Int): String? {
        require(level in PageQuality.LEVELS) { "level $level is not a ProofreadPage quality level" }
        val parts = ProofreadPageParts.decompose(text) ?: return null
        val current = parts.header.quality
        if (current?.level == level) return text
        val quality = (current ?: PageQuality(level, "")).copy(level = level)
        return parts.copy(header = parts.header.copy(quality = quality)).compose()
    }
}
