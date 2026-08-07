package org.limepepper.lang.wikitext.editing.surround

import com.intellij.openapi.editor.Editor
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.TextRange
import org.limepepper.lang.wikitext.editing.WtEditingFlags
import org.limepepper.lang.wikitext.editing.WtWrapTag

/**
 * Performs the actual wrapping of the editor's selection in a [WtWrapTag].
 *
 * The seam that makes the surround feature swappable: a [WtTagSurrounder] only
 * knows *which* construct it offers, never *how* the text gets in. Every
 * implementation renders its markup through
 * [org.limepepper.lang.wikitext.editing.WtWrapRenderer], so they are
 * indistinguishable in the resulting document and differ only in interaction —
 * which is exactly the axis we want to compare while prototyping.
 *
 * Selecting one is [WtEditingFlags.surroundStrategy]'s job; see [forCurrentFlags].
 */
interface WtWrapExecutor {
    /**
     * Wraps the current selection of [editor] in [tag].
     *
     * Called from inside the platform's surround write command. Returns the
     * range the caller should select afterwards, or null when the
     * implementation drives the caret itself (live templates do) or defers its
     * work outside the current write action (the dialog prompt does).
     */
    fun wrap(project: Project, editor: Editor, tag: WtWrapTag): TextRange?

    companion object {
        /** The executor the registry currently points at. Read per invocation
         *  so flipping the key takes effect without restarting the IDE. */
        fun forCurrentFlags(): WtWrapExecutor =
            when (WtEditingFlags.surroundStrategy()) {
                WtEditingFlags.SurroundStrategy.TEMPLATE -> WtTemplateWrapExecutor()
                WtEditingFlags.SurroundStrategy.DOCUMENT -> WtDocumentWrapExecutor()
            }
    }
}
