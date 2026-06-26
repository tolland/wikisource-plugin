package org.limepepper.lang.wikitext.structure

import com.intellij.ide.projectView.PresentationData
import com.intellij.ide.structureView.StructureViewTreeElement
import com.intellij.ide.util.treeView.smartTree.SortableTreeElement
import com.intellij.ide.util.treeView.smartTree.TreeElement
import com.intellij.navigation.ItemPresentation
import com.intellij.psi.NavigatablePsiElement


class WtStructureViewElement(val element: NavigatablePsiElement) : StructureViewTreeElement,
    SortableTreeElement {
    override fun getValue(): Any {
        return element
    }

    override fun navigate(requestFocus: Boolean) {
        element.navigate(requestFocus);
    }

    override fun getPresentation(): ItemPresentation = element.presentation ?: PresentationData()

    override fun getChildren(): Array<out TreeElement?> {

//        if (element is GdbFile) {
//            return element.commands.map(::GdbStructureViewElement).toTypedArray()
//        } else {
//            return emptyArray()
//        }
        return emptyArray()
    }

    override fun getAlphaSortKey(): String = element.name.orEmpty()

}
