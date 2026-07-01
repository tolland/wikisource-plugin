package org.limepepper.lang.wikitext.tool

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.FileEditorManagerEvent
import com.intellij.openapi.fileEditor.FileEditorManagerListener
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileManager
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.ui.content.ContentFactory
import com.intellij.ui.treeStructure.Tree
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.WtVirtualFileSystem
import org.limepepper.lang.wikitext.vfs.backend.ChildNode
import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.awt.BorderLayout
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import javax.swing.JButton
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.JSplitPane
import javax.swing.SwingUtilities
import javax.swing.event.TreeExpansionEvent
import javax.swing.event.TreeWillExpandListener
import javax.swing.tree.DefaultMutableTreeNode
import javax.swing.tree.DefaultTreeModel

private val LOG = logger<MyToolWindowFactory>()

class MyToolWindowFactory : ToolWindowFactory {

    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val contentFactory = ContentFactory.getInstance()
        toolWindow.contentManager.addContent(
            contentFactory.createContent(buildBrowserTab(project, toolWindow), "Browser", false)
        )
        toolWindow.contentManager.addContent(
            contentFactory.createContent(buildDebugTab(), "Debug", false)
        )
    }

    // -------------------------------------------------------------------------
    // Tab 1 — VFS browser
    // -------------------------------------------------------------------------

    private fun buildBrowserTab(project: Project, toolWindow: ToolWindow): JPanel {
        val fs: WtVirtualFileSystem? = VirtualFileManager.getInstance()
            .getFileSystem(WtVirtualFileSystem.PROTOCOL) as? WtVirtualFileSystem

        val rootNode = DefaultMutableTreeNode("wikisource://")
        rootNode.add(DefaultMutableTreeNode(LOADING))
        val model = DefaultTreeModel(rootNode)
        val tree = Tree(model)
        tree.isRootVisible = true

        tree.addMouseListener(object : MouseAdapter() {
            override fun mouseClicked(e: MouseEvent) {
                if (e.clickCount != 2) return
                val node = tree.lastSelectedPathComponent as? DefaultMutableTreeNode ?: return
                val vFile = node.userObject as? WtVirtualFile ?: return
                if (!vFile.isDirectory) {
                    FileEditorManager.getInstance(project).openFile(vFile, true)
                }
            }
        })

        tree.addTreeWillExpandListener(object : TreeWillExpandListener {
            override fun treeWillExpand(event: TreeExpansionEvent) {
                val node = event.path.lastPathComponent as? DefaultMutableTreeNode ?: return
                val vFile = node.userObject as? WtVirtualFile ?: return
                if (!vFile.isDirectory) return
                val firstChild = node.firstChild as? DefaultMutableTreeNode ?: return
                if (firstChild.userObject != PLACEHOLDER) return
                expandNode(node, vFile, model, fs)
            }
            override fun treeWillCollapse(event: TreeExpansionEvent) {}
        })

        val propertiesArea = JBTextArea(8, 60).apply {
            isEditable = false
            font = java.awt.Font(java.awt.Font.MONOSPACED, java.awt.Font.PLAIN, 12)
            text = "Select a file to see its properties."
        }

        tree.addTreeSelectionListener {
            val node = tree.lastSelectedPathComponent as? DefaultMutableTreeNode ?: return@addTreeSelectionListener
            val vFile = node.userObject as? WtVirtualFile ?: return@addTreeSelectionListener
            showProperties(vFile, propertiesArea)
        }

        project.messageBus.connect(toolWindow.disposable).subscribe(
            FileEditorManagerListener.FILE_EDITOR_MANAGER,
            object : FileEditorManagerListener {
                override fun selectionChanged(event: FileEditorManagerEvent) {
                    val file = event.newFile as? WtVirtualFile ?: return
                    showProperties(file, propertiesArea)
                }
            },
        )

        val split = JSplitPane(JSplitPane.VERTICAL_SPLIT, JBScrollPane(tree), JBScrollPane(propertiesArea))
        split.resizeWeight = 0.75

        val panel = JPanel(BorderLayout())
        panel.add(split, BorderLayout.CENTER)

        ApplicationManager.getApplication().executeOnPooledThread {
            populateRoot(rootNode, model, fs)
        }

        return panel
    }

    private fun showProperties(vFile: WtVirtualFile, area: JBTextArea) {
        area.text = "Loading properties for ${vFile.path} …"
        ApplicationManager.getApplication().executeOnPooledThread {
            val text = try {
                val stat = WtVfsService.instance.backend.stat(vFile.path)
                buildString {
                    appendLine("name:      ${stat.name ?: vFile.name}")
                    appendLine("path:      ${stat.path}")
                    appendLine("kind:      ${if (vFile.isDirectory) NodeKind.directory else NodeKind.file}")
                    appendLine("exists:    ${stat.exists}")
                    appendLine("stableId:  ${stat.stableId ?: vFile.stableId}")
                    appendLine("revid:     ${stat.revid ?: vFile.revid}")
                    appendLine("timestamp: ${stat.timestamp ?: "—"}")
                    appendLine("length:    ${stat.length ?: "—"}")
                    appendLine("writable:  ${vFile.isWritable}")
                }
            } catch (e: VfsBackendException) {
                "⚠ failed to stat ${vFile.path}: ${e.message}"
            }
            SwingUtilities.invokeLater { area.text = text }
        }
    }

    private fun toVFile(fs: WtVirtualFileSystem, child: ChildNode, parent: WtVirtualFile?): WtVirtualFile =
        fs.getOrCreate(
            path = child.path,
            name = child.name,
            isDir = child.kind == NodeKind.directory,
            parent = parent,
            stableId = child.stableId,
            revid = child.revid,
        )

    private fun populateRoot(
        rootNode: DefaultMutableTreeNode,
        model: DefaultTreeModel,
        fs: WtVirtualFileSystem?,
    ) {
        val backend = WtVfsService.instance.backend
        try {
            val result = backend.listChildren("/")
            SwingUtilities.invokeLater {
                rootNode.removeAllChildren()
                for (child in result.children) {
                    val vFile: WtVirtualFile? = fs?.let { toVFile(it, child, null) }
                    val node = fileNode(vFile, child.name)
                    try {
                        val sub = backend.listChildren(child.path)
                        for (gc in sub.children) {
                            val gvFile: WtVirtualFile? = fs?.let { toVFile(it, gc, vFile) }
                            val gNode = fileNode(gvFile, gc.name)
                            if (gc.kind == NodeKind.directory) gNode.add(DefaultMutableTreeNode(PLACEHOLDER))
                            node.add(gNode)
                        }
                    } catch (_: VfsBackendException) {
                        node.add(DefaultMutableTreeNode(PLACEHOLDER))
                    }
                    rootNode.add(node)
                }
                model.reload(rootNode)
            }
        } catch (e: VfsBackendException) {
            LOG.warn("VFS root load failed", e)
            SwingUtilities.invokeLater {
                rootNode.removeAllChildren()
                rootNode.add(DefaultMutableTreeNode("⚠ sidecar not running (${e.message})"))
                model.reload(rootNode)
            }
        }
    }

    private fun expandNode(
        node: DefaultMutableTreeNode,
        vFile: WtVirtualFile,
        model: DefaultTreeModel,
        fs: WtVirtualFileSystem?,
    ) {
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val result = WtVfsService.instance.backend.listChildren(vFile.path)
                val builtChildren = mutableListOf<WtVirtualFile>()
                val childNodes = result.children.map { child ->
                    val childFile: WtVirtualFile? = fs?.let { toVFile(it, child, vFile) }
                    if (childFile != null) builtChildren.add(childFile)
                    val childNode = fileNode(childFile, child.name)
                    if (child.kind == NodeKind.directory) childNode.add(DefaultMutableTreeNode(PLACEHOLDER))
                    childNode
                }
                @Suppress("UNCHECKED_CAST")
                vFile.cachedChildren = builtChildren.toTypedArray() as Array<VirtualFile>
                SwingUtilities.invokeLater {
                    node.removeAllChildren()
                    childNodes.forEach { node.add(it) }
                    model.reload(node)
                }
            } catch (e: VfsBackendException) {
                LOG.warn("VFS children load failed for ${vFile.path}", e)
                SwingUtilities.invokeLater {
                    node.removeAllChildren()
                    node.add(DefaultMutableTreeNode("⚠ ${e.message}"))
                    model.reload(node)
                }
            }
        }
    }

    // -------------------------------------------------------------------------
    // Tab 2 — Debug panel
    // -------------------------------------------------------------------------

    private fun buildDebugTab(): JPanel {
        val statusLabel = JLabel("Status: checking…")
        val infoArea = JBTextArea(20, 60).apply {
            isEditable = false
            font = java.awt.Font(java.awt.Font.MONOSPACED, java.awt.Font.PLAIN, 12)
        }
        val refreshButton = JButton("Refresh").apply {
            addActionListener {
                ApplicationManager.getApplication().executeOnPooledThread {
                    checkBackend(statusLabel, infoArea)
                }
            }
        }
        val top = JPanel(BorderLayout())
        top.add(statusLabel, BorderLayout.CENTER)
        top.add(refreshButton, BorderLayout.EAST)

        val panel = JPanel(BorderLayout())
        panel.add(top, BorderLayout.NORTH)
        panel.add(JBScrollPane(infoArea), BorderLayout.CENTER)

        ApplicationManager.getApplication().executeOnPooledThread {
            checkBackend(statusLabel, infoArea)
        }
        return panel
    }

    private fun checkBackend(label: JLabel, area: JBTextArea) {
        val backend = WtVfsService.instance.backend
        try {
            val root = backend.stat("/")
            val sites = backend.listChildren("/")
            val sb = StringBuilder()
            sb.appendLine("stat /  →  exists=${root.exists}  kind=${root.kind}")
            sb.appendLine()
            sb.appendLine("Sites (${sites.children.size}):")
            for (site in sites.children) {
                sb.appendLine("  ${site.path}  [${site.kind}]  stableId=${site.stableId}")
                try {
                    val indexes = backend.listChildren(site.path)
                    for (idx in indexes.children) {
                        sb.appendLine("    ${idx.name}  [${idx.kind}]  stableId=${idx.stableId}")
                        try {
                            val containers = backend.listChildren(idx.path)
                            for (c in containers.children) {
                                sb.appendLine("      ${c.name}  [${c.kind}]")
                            }
                        } catch (_: VfsBackendException) {}
                    }
                } catch (_: VfsBackendException) {}
            }
            SwingUtilities.invokeLater {
                label.text = "Status: ✓ connected"
                area.text = sb.toString()
            }
        } catch (e: VfsBackendException) {
            SwingUtilities.invokeLater {
                label.text = "Status: ✗ offline — ${e.message}"
                area.text = ""
            }
        }
    }

    // -------------------------------------------------------------------------

    companion object {
        private const val LOADING = "Loading…"
        private const val PLACEHOLDER = "…"

        private fun fileNode(vFile: WtVirtualFile?, fallbackName: String): DefaultMutableTreeNode =
            object : DefaultMutableTreeNode(vFile) {
                override fun toString(): String {
                    val f = userObject as? WtVirtualFile
                    val icon = if (f?.isDirectory == true) "📁 " else "📄 "
                    return icon + (f?.name ?: fallbackName)
                }
            }
    }
}
