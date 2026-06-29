package org.limepepper.lang.wikitext.tool

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.content.ContentFactory
import com.intellij.ui.treeStructure.Tree
import org.limepepper.lang.wikitext.vfs.backend.ChildNode
import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import javax.swing.SwingUtilities
import javax.swing.tree.DefaultMutableTreeNode
import javax.swing.tree.DefaultTreeModel

private val LOG = logger<MyToolWindowFactory>()

/**
 * Tool window that renders the live VFS tree from the wtbot sidecar.
 *
 * Tree is populated on a background thread after the window opens; the root
 * shows "Loading…" until the first response arrives. Each directory node
 * lazy-loads its children on first expansion (via a placeholder child).
 *
 * Double-clicking a file node is intentionally a no-op for now — editor
 * integration comes after the VFS write wiring is complete.
 */
class MyToolWindowFactory : ToolWindowFactory {

    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val rootNode = DefaultMutableTreeNode("wikisource://")
        val loading = DefaultMutableTreeNode("Loading…")
        rootNode.add(loading)

        val model = DefaultTreeModel(rootNode)
        val tree = Tree(model)
        tree.isRootVisible = true

        tree.addMouseListener(object : MouseAdapter() {
            override fun mouseClicked(e: MouseEvent) {
                if (e.clickCount != 2) return
                val node = tree.lastSelectedPathComponent as? DefaultMutableTreeNode ?: return
                val data = node.userObject as? ChildNode ?: return
                if (data.kind == NodeKind.file) {
                    // editor wiring comes in next slice
                    LOG.info("VFS: selected file ${data.path}")
                }
            }
        })

        // Lazy-load children when a directory node is expanded
        tree.addTreeWillExpandListener(object : javax.swing.event.TreeWillExpandListener {
            override fun treeWillExpand(event: javax.swing.event.TreeExpansionEvent) {
                val node = event.path.lastPathComponent as? DefaultMutableTreeNode ?: return
                val data = node.userObject as? ChildNode ?: return
                if (data.kind != NodeKind.directory) return
                val firstChild = node.firstChild as? DefaultMutableTreeNode ?: return
                if (firstChild.userObject != PLACEHOLDER) return
                loadChildren(node, data.path, model)
            }

            override fun treeWillCollapse(event: javax.swing.event.TreeExpansionEvent) {}
        })

        val content = ContentFactory.getInstance()
            .createContent(JBScrollPane(tree), "", false)
        toolWindow.contentManager.addContent(content)

        // Kick off the initial root load in the background
        ApplicationManager.getApplication().executeOnPooledThread {
            loadRootAsync(rootNode, loading, model)
        }
    }

    private fun loadRootAsync(
        rootNode: DefaultMutableTreeNode,
        loadingNode: DefaultMutableTreeNode,
        model: DefaultTreeModel,
    ) {
        val backend = WtVfsService.instance.backend
        try {
            val result = backend.listChildren("/")
            SwingUtilities.invokeLater {
                rootNode.remove(loadingNode)
                for (child in result.children) {
                    val siteNode = labelNode(child)
                    // pre-populate one level so the expand arrow appears
                    loadDirectChildren(siteNode, child.path, backend)
                    rootNode.add(siteNode)
                }
                model.reload(rootNode)
            }
        } catch (e: VfsBackendException) {
            LOG.warn("VFS root load failed", e)
            SwingUtilities.invokeLater {
                rootNode.remove(loadingNode)
                rootNode.add(DefaultMutableTreeNode("⚠ sidecar not running (${e.message})"))
                model.reload(rootNode)
            }
        }
    }

    private fun loadChildren(
        parentNode: DefaultMutableTreeNode,
        path: String,
        model: DefaultTreeModel,
    ) {
        val backend = WtVfsService.instance.backend
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val result = backend.listChildren(path)
                SwingUtilities.invokeLater {
                    parentNode.removeAllChildren()
                    for (child in result.children) {
                        val node = labelNode(child)
                        if (child.kind == NodeKind.directory) node.add(DefaultMutableTreeNode(PLACEHOLDER))
                        parentNode.add(node)
                    }
                    model.reload(parentNode)
                }
            } catch (e: VfsBackendException) {
                LOG.warn("VFS children load failed for $path", e)

//                SwingUtilities.invokeLater {
//                    parentNode.removeAllChildren()
//                    parentNode.add(DefaultMutableTreeNode("⚠ failed to load children"))
//                    model.reload(parentNode)
//                }
            }
        }
    }

    private fun loadDirectChildren(
        parentNode: DefaultMutableTreeNode,
        path: String,
        backend: org.limepepper.lang.wikitext.vfs.backend.VfsBackend,
    ) {
        try {
            val result = backend.listChildren(path)
            for (child in result.children) {
                val node = labelNode(child)
                if (child.kind == NodeKind.directory) node.add(DefaultMutableTreeNode(PLACEHOLDER))
                parentNode.add(node)
            }
        } catch (e: VfsBackendException) {
            LOG.warn("VFS prefetch failed for $path", e)
            parentNode.add(DefaultMutableTreeNode(PLACEHOLDER))
        }
    }

    companion object {
        private const val PLACEHOLDER = "…"

        private fun labelNode(child: ChildNode): DefaultMutableTreeNode =
            object : DefaultMutableTreeNode(child) {
                override fun toString(): String {
                    val icon = if (child.kind == NodeKind.directory) "📁 " else "📄 "
                    return icon + child.name
                }
            }
    }
}
