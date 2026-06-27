package org.limepepper.lang.wikitext.structure

import com.intellij.ide.projectView.PresentationData
import com.intellij.ide.structureView.StructureViewTreeElement
import com.intellij.ide.util.treeView.smartTree.SortableTreeElement
import com.intellij.ide.util.treeView.smartTree.TreeElement
import com.intellij.navigation.ItemPresentation
import com.intellij.psi.NavigatablePsiElement
import com.intellij.psi.PsiElement
import org.limepepper.lang.wikitext.psi.WtHeading
import org.limepepper.lang.wikitext.psi.WtFile
import org.limepepper.lang.wikitext.psi.WtInlineItem
import org.limepepper.lang.wikitext.psi.WtInternalLink
import org.limepepper.lang.wikitext.psi.WtParagraph
import org.limepepper.lang.wikitext.psi.WtTemplate


class WtStructureViewElement(val element: NavigatablePsiElement) : StructureViewTreeElement,
    SortableTreeElement {

    override fun getValue(): Any {
        return element
    }

    override fun navigate(requestFocus: Boolean) {
        element.navigate(requestFocus)
    }

    override fun getPresentation(): ItemPresentation =
        element.presentation ?: PresentationData(presentableText(), null, element.getIcon(0), null)

    override fun getChildren(): Array<out TreeElement?> {
        return structureChildren()
            .map(::WtStructureViewElement)
            .toTypedArray()
    }

    override fun getAlphaSortKey(): String = presentableText()

    private fun structureChildren(): List<NavigatablePsiElement> =
        when (element) {
            is WtFile -> element.children.filterIsInstance<NavigatablePsiElement>()
            is WtHeading -> element.inlineItemList
            is WtParagraph -> element.inlineItemList
            is WtInlineItem -> listOfNotNull(
                element.internalLink,
                element.htmlTag,
                element.verbatimTag,
                element.template
            )
            is WtInternalLink -> element.inlineItemList
            is WtTemplate -> element.inlineItemList
            else -> emptyList()
        }

    private fun presentableText(): String =
        when (element) {
            is WtFile -> element.name
            is WtHeading -> "H${element.level}: ${element.trimmedText()}"
            is WtParagraph -> element.trimmedText()
            is WtTemplate -> "{{${element.templateName?.text?.trim().orEmpty()}}}"
            is WtInternalLink -> "[[${element.linkTarget?.text?.trim().orEmpty()}]]"
            is WtInlineItem -> element.trimmedText()
            else -> element.name ?: element.trimmedText()
        }.ifBlank { element.toString() }

    private fun PsiElement.trimmedText(): String =
        text
            .replace(Regex("\\s+"), " ")
            .trim()
            .let { if (it.length > MAX_PRESENTATION_LENGTH) it.take(MAX_PRESENTATION_LENGTH - 1) + "..." else it }

    companion object {
        private const val MAX_PRESENTATION_LENGTH = 80
    }

}
