package org.limepepper.lang.wikitext.tree

import com.intellij.ide.projectView.TreeStructureProvider
import com.intellij.ide.projectView.ViewSettings
import com.intellij.ide.projectView.impl.nodes.PsiFileNode
import com.intellij.ide.util.treeView.AbstractTreeNode
import com.intellij.openapi.fileTypes.PlainTextFileType


internal class WtTreeStructureProvider : TreeStructureProvider {
    override fun modify(
        parent: AbstractTreeNode<*>,
        children: MutableCollection<AbstractTreeNode<*>?>,
        settings: ViewSettings?
    ): MutableCollection<AbstractTreeNode<*>?> {
        val nodes = ArrayList<AbstractTreeNode<*>?>()
        for (child in children) {
            if (child is PsiFileNode) {
                val file = child.getVirtualFile()
                if (file != null && !file.isDirectory() && (file.getFileType() !is PlainTextFileType)) {
                    continue
                }
            }
            nodes.add(child)
        }
        return nodes
    }
}