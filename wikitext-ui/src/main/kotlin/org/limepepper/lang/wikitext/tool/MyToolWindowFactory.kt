package org.limepepper.lang.wikitext.tool

import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.content.ContentFactory
import com.intellij.ui.treeStructure.Tree
import org.limepepper.lang.wikitext.vfs.INSTANCE
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import javax.swing.tree.DefaultMutableTreeNode
import javax.swing.tree.DefaultTreeModel

/**
 * Renders the (currently hardcoded) WtVirtualFileSystem tree in a tool window.
 * Double-clicking a leaf opens it in an editor tab via FileEditorManager --
 * which is what gets the wikitext PSI/lexer/annotator stack applied to the
 * dummy content for free, proving the whole vertical end to end.
 *
 * This is the DataGrip Database-Explorer pattern: a custom tree of domain
 * nodes in a tool window, opening real editor tabs on activation, with NOTHING
 * injected into the Project view.
 */
class MyToolWindowFactory : ToolWindowFactory {

    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val fs = INSTANCE
        val root = fs.dummyRoot

        val rootNode = buildNode(root)
        val tree = Tree(DefaultTreeModel(rootNode))

        tree.addMouseListener(object : MouseAdapter() {
            override fun mouseClicked(e: MouseEvent) {
                if (e.clickCount != 2) return
                val node = tree.lastSelectedPathComponent as? DefaultMutableTreeNode ?: return
                val vFile = node.userObject as? VirtualFile ?: return
                if (!vFile.isDirectory) {
                    FileEditorManager.getInstance(project).openFile(vFile, true)
                }
            }
        })

        val content = ContentFactory.getInstance()
            .createContent(JBScrollPane(tree), "", false)
        toolWindow.contentManager.addContent(content)
    }

    private fun buildNode(file: VirtualFile): DefaultMutableTreeNode {
        val node = object : DefaultMutableTreeNode(file) {
            override fun toString(): String = file.name
        }
        if (file.isDirectory) {
            file.children.forEach { node.add(buildNode(it)) }
        }
        return node
    }
}
