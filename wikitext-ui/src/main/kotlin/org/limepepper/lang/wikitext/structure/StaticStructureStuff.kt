package org.limepepper.lang.wikitext.structure

import com.intellij.ide.structureView.FileEditorPositionListener
import com.intellij.ide.structureView.ModelListener
import com.intellij.ide.structureView.StructureViewModel
import com.intellij.ide.structureView.StructureViewTreeElement
import com.intellij.ide.util.treeView.smartTree.Filter
import com.intellij.ide.util.treeView.smartTree.Grouper
import com.intellij.ide.util.treeView.smartTree.Sorter
import com.intellij.navigation.ItemPresentation
import javax.swing.Icon

class StaticStructureStuff {
}


class StaticNode(
    private val name: String,
    private val children: List<StaticNode> = emptyList(),
) : StructureViewTreeElement {

    override fun getValue(): Any = this

    override fun getChildren(): Array<StructureViewTreeElement> =
        children.toTypedArray()

    override fun navigate(requestFocus: Boolean) {
        // Later: navigate/select something in your custom FileEditor.
    }

    override fun canNavigate(): Boolean = false

    override fun canNavigateToSource(): Boolean = false

    override fun getPresentation(): ItemPresentation =
        object : ItemPresentation {
            override fun getPresentableText(): String = name

            override fun getLocationString(): String? = null

            override fun getIcon(unused: Boolean): Icon? = null
        }
}

class StaticStructureViewModel : StructureViewModel {

    private val root = StaticNode(
        "Root",
        listOf(
            StaticNode(
                "Index",
                listOf(
                    StaticNode("Index body"),
                    StaticNode("Metadata"),
                ),
            ),
            StaticNode(
                "Pages",
                listOf(
                    StaticNode("Page 1"),
                    StaticNode("Page 2"),
                    StaticNode("Page 3"),
                ),
            ),
        ),
    )

    override fun getCurrentEditorElement(): Any? {
        TODO("Not yet implemented")
    }

    override fun addEditorPositionListener(listener: FileEditorPositionListener) {
        TODO("Not yet implemented")
    }

    override fun removeEditorPositionListener(listener: FileEditorPositionListener) {
        TODO("Not yet implemented")
    }

    override fun addModelListener(modelListener: ModelListener) {
        TODO("Not yet implemented")
    }

    override fun removeModelListener(modelListener: ModelListener) {
        TODO("Not yet implemented")
    }

    override fun getRoot(): StructureViewTreeElement = root
    override fun getGroupers(): Array<out Grouper?> {
        TODO("Not yet implemented")
    }

    override fun getSorters(): Array<out Sorter?> {
        TODO("Not yet implemented")
    }

    override fun getFilters(): Array<out Filter?> {
        TODO("Not yet implemented")
    }


    override fun shouldEnterElement(element: Any?): Boolean = false

    override fun dispose() {
    }
}
