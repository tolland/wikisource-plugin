package org.limepepper.lang.wikitext.editing.surround

import com.intellij.lang.surroundWith.Surrounder
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.TextRange
import com.intellij.psi.PsiElement
import org.limepepper.lang.wikitext.editing.WtWrapTag

/**
 * One entry in the Surround With popup, for one [WtWrapTag].
 *
 * Parameterized rather than subclassed per construct: adding `<poem>` should
 * mean adding a line to [WtWrapTag], not writing another class. All the
 * behaviour lives in the injected [WtWrapExecutor], which is what makes the
 * interaction style swappable at runtime.
 */
class WtTagSurrounder(
    private val tag: WtWrapTag,
    private val executor: WtWrapExecutor,
) : Surrounder {

    override fun getTemplateDescription(): String = tag.title

    /**
     * Always applicable. Wikitext is prose: unlike a statement-oriented
     * language there is no arrangement of elements that makes wrapping text in
     * `<nowiki>` meaningless, and disabling entries here would only produce a
     * popup whose contents change for reasons the user cannot see.
     */
    override fun isApplicable(elements: Array<out PsiElement>): Boolean = true

    override fun surroundElements(
        project: Project,
        editor: Editor,
        elements: Array<out PsiElement>,
    ): TextRange? = executor.wrap(project, editor, tag)
}
