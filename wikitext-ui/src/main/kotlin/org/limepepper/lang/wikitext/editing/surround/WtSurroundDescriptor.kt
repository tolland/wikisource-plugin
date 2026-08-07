package org.limepepper.lang.wikitext.editing.surround

import com.intellij.lang.surroundWith.SurroundDescriptor
import com.intellij.lang.surroundWith.Surrounder
import com.intellij.psi.PsiElement
import com.intellij.psi.PsiFile
import org.limepepper.lang.wikitext.editing.WtEditingFlags
import org.limepepper.lang.wikitext.editing.WtWrapTagSets

/**
 * Contributes wikitext constructs to Surround With (Ctrl+Alt+T).
 *
 * Registered on the Wikitext language, so it applies equally to plain `.wt`
 * files and to `wikisource://` files — the whole feature is a
 * [com.intellij.openapi.editor.Document] operation, and `WtVirtualFile` already
 * routes saves through the VFS backend, so there is nothing VFS-specific to do
 * here.
 */
class WtSurroundDescriptor : SurroundDescriptor {

    /**
     * The elements the popup is offered for.
     *
     * Statement-oriented languages use this to refuse nonsensical selections.
     * Wikitext has no such structure — any run of characters is wrappable — so
     * this returns whatever PSI happens to intersect the range, and falls back
     * to the file itself rather than returning the empty array that would
     * silently disable the action. The surrounders work from the editor
     * selection regardless; these elements exist only to satisfy the contract.
     */
    override fun getElementsToSurround(file: PsiFile, startOffset: Int, endOffset: Int): Array<PsiElement> {
        if (!WtEditingFlags.surroundEnabled()) return PsiElement.EMPTY_ARRAY
        val start = file.findElementAt(startOffset)
        val end = file.findElementAt((endOffset - 1).coerceAtLeast(startOffset))
        return listOfNotNull(start, end).distinct().toTypedArray().ifEmpty { arrayOf(file) }
    }

    /**
     * Rebuilt per call rather than cached, so flipping the strategy registry
     * key changes the next popup without an IDE restart.
     */
    override fun getSurrounders(): Array<Surrounder> {
        if (!WtEditingFlags.surroundEnabled()) return emptyArray()
        val executor = WtWrapExecutor.forCurrentFlags()
        return WtWrapTagSets.surroundWith
            .map { WtTagSurrounder(it, executor) }
            .toTypedArray()
    }

    /** False: platform surrounders (live templates, etc) stay in the popup. */
    override fun isExclusive(): Boolean = false
}
