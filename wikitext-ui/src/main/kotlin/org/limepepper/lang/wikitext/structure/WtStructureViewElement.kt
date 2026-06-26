package org.limepepper.lang.wikitext.structure

import com.intellij.ide.projectView.PresentationData
import com.intellij.ide.structureView.StructureViewTreeElement
import com.intellij.ide.util.treeView.smartTree.SortableTreeElement
import com.intellij.ide.util.treeView.smartTree.TreeElement
import com.intellij.navigation.ItemPresentation
import com.intellij.psi.NavigatablePsiElement
import org.limepepper.lang.wikitext.psi.WtFile


class WtStructureViewElement(val element: NavigatablePsiElement) : StructureViewTreeElement,
    SortableTreeElement {

    override fun getValue(): Any {
        return "element: ${element.name}"
    }

    override fun navigate(requestFocus: Boolean) {
        element.navigate(requestFocus);
    }

    override fun getPresentation(): ItemPresentation = element.presentation ?: PresentationData()

    override fun getChildren(): Array<out TreeElement?> {

        return if (element is WtFile) {
            element.commands.map<_, TreeElement>(::WtStructureViewElement).toTypedArray()
        } else {
            println("No children for element: $element")
            emptyArray()
        }
    }

    override fun getAlphaSortKey(): String = element.name.orEmpty()

}
