package org.limepepper.lang.wikitext.tool

import com.intellij.icons.AllIcons
import com.intellij.ide.util.treeView.NodeDescriptor
import com.intellij.ide.util.treeView.TreeState
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.DefaultActionGroup
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.fileEditor.FileEditorManagerEvent
import com.intellij.openapi.fileEditor.FileEditorManagerListener
import com.intellij.openapi.ide.CopyPasteManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFileManager
import com.intellij.openapi.wm.ToolWindow
import com.intellij.ui.ColoredTreeCellRenderer
import com.intellij.ui.JBColor
import com.intellij.ui.PopupHandler
import com.intellij.ui.SimpleTextAttributes
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.ui.tree.AsyncTreeModel
import com.intellij.ui.tree.StructureTreeModel
import com.intellij.ui.treeStructure.Tree
import com.intellij.util.ui.tree.TreeUtil
import org.limepepper.lang.wikitext.WtFileType
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.WtVirtualFileSystem
import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.awt.BorderLayout
import java.awt.datatransfer.StringSelection
import java.awt.event.MouseAdapter
import java.awt.event.MouseEvent
import javax.swing.JButton
import javax.swing.JPanel
import javax.swing.JSplitPane
import javax.swing.JTree
import javax.swing.SwingUtilities

internal class WikisourceBrowserToolWindowTab(
    private val project: Project,
    private val toolWindow: ToolWindow,
) {

    fun createComponent(): JPanel {
        val fs: WtVirtualFileSystem? = VirtualFileManager.getInstance()
            .getFileSystem(WtVirtualFileSystem.PROTOCOL) as? WtVirtualFileSystem

        // StructureTreeModel computes children on a background invoker thread
        // (blocking sidecar calls are fine there); AsyncTreeModel marshals the
        // results to the EDT and keeps expansion/selection stable across
        // invalidations because the structure's elements are the path-cached
        // WtVirtualFile instances.
        val structure = WikisourceTreeStructure(fs)
        val structureModel = StructureTreeModel(structure, toolWindow.disposable)
        val tree = Tree(AsyncTreeModel(structureModel, toolWindow.disposable))
        tree.isRootVisible = true
        tree.cellRenderer = object : ColoredTreeCellRenderer() {
            override fun customizeCellRenderer(
                tree: JTree,
                value: Any?,
                selected: Boolean,
                expanded: Boolean,
                leaf: Boolean,
                row: Int,
                hasFocus: Boolean,
            ) {
                when (val element = elementOf(value)) {
                    is WtVirtualFile -> {
                        icon = if (element.isDirectory) AllIcons.Nodes.Folder else WtFileType.icon
                        // Dirty (uncommitted EditJournal edits) renders like a
                        // modified file in VCS: blue name plus a star. A
                        // placeholder (page not created on the wiki yet) is
                        // grey italic until it has local edits.
                        val nameAttributes = when {
                            element.dirty -> DIRTY_ATTRIBUTES
                            element.placeholder -> SimpleTextAttributes.GRAYED_ITALIC_ATTRIBUTES
                            else -> SimpleTextAttributes.REGULAR_ATTRIBUTES
                        }
                        append(displayLabel(element.name), nameAttributes)
                        if (element.dirty) append(" *", DIRTY_ATTRIBUTES)
                        // ProofreadPage quality bullet in the pagelist colours.
                        element.qualityLevel?.let { level ->
                            append(
                                "  ●",
                                SimpleTextAttributes(
                                    SimpleTextAttributes.STYLE_PLAIN,
                                    qualityColor(level),
                                ),
                            )
                        }
                    }
                    else -> {
                        icon = null
                        append(element?.toString() ?: "")
                    }
                }
            }
        }

        tree.addMouseListener(object : MouseAdapter() {
            override fun mouseClicked(e: MouseEvent) {
                if (e.clickCount != 2) return
                val vFile = elementOf(tree.lastSelectedPathComponent) as? WtVirtualFile ?: return
                if (!vFile.isDirectory) {
                    FileEditorManager.getInstance(project).openFile(vFile, true)
                }
            }
        })

        val propertiesArea = JBTextArea(8, 60).apply {
            isEditable = false
            font = java.awt.Font(java.awt.Font.MONOSPACED, java.awt.Font.PLAIN, 12)
            text = "Select a file to see its properties."
        }

        tree.addTreeSelectionListener {
            val vFile = elementOf(tree.lastSelectedPathComponent) as? WtVirtualFile
                ?: return@addTreeSelectionListener
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

        installContextMenu(tree, structureModel, propertiesArea)

        val refreshButton = JButton("Refresh").apply {
            addActionListener {
                refreshTreePreservingState(tree, structureModel, fs)
            }
        }
        val toolbar = JPanel(BorderLayout()).apply { add(refreshButton, BorderLayout.WEST) }

        val split = JSplitPane(JSplitPane.VERTICAL_SPLIT, JBScrollPane(tree), JBScrollPane(propertiesArea))
        split.resizeWeight = 0.75

        val panel = JPanel(BorderLayout())
        panel.add(toolbar, BorderLayout.NORTH)
        panel.add(split, BorderLayout.CENTER)

        TreeUtil.promiseExpand(tree, 1)

        return panel
    }

    /** Stub menu: no cut/paste (VFS is read-only) - just open/copy-path/refresh-one. */
    private fun installContextMenu(
        tree: Tree,
        structureModel: StructureTreeModel<WikisourceTreeStructure>,
        propertiesArea: JBTextArea,
    ) {
        fun selectedFile(): WtVirtualFile? =
            elementOf(tree.lastSelectedPathComponent) as? WtVirtualFile

        val group = DefaultActionGroup().apply {
            add(object : AnAction("Open") {
                override fun actionPerformed(e: AnActionEvent) {
                    val vFile = selectedFile() ?: return
                    if (!vFile.isDirectory) FileEditorManager.getInstance(project).openFile(vFile, true)
                }
            })
            add(object : AnAction("Copy Path") {
                override fun actionPerformed(e: AnActionEvent) {
                    val vFile = selectedFile() ?: return
                    CopyPasteManager.getInstance().setContents(StringSelection(vFile.path))
                }
            })
            add(object : AnAction("Refresh") {
                override fun actionPerformed(e: AnActionEvent) {
                    val vFile = selectedFile() ?: return
                    ApplicationManager.getApplication().executeOnPooledThread {
                        try {
                            val stat = WtVfsService.instance.backend.stat(vFile.path)
                            if (stat.exists) vFile.invalidateIfStale(stat)
                        } catch (_: VfsBackendException) {
                            // Backend unreachable - leave cached state as-is.
                        }
                        // Non-invalidated directories re-list from their
                        // in-memory cachedChildren, so this is cheap.
                        structureModel.invalidateAsync()
                        SwingUtilities.invokeLater {
                            showProperties(vFile, propertiesArea)
                        }
                    }
                }
            })
        }
        PopupHandler.installPopupMenu(tree, group, "WikisourceVfsTreePopup")
    }

    /** Reflects the in-memory [WtVirtualFile] state - not a fresh backend query. */
    private fun showProperties(vFile: WtVirtualFile, area: JBTextArea) {
        area.text = buildString {
            appendLine("name:      ${vFile.name}")
            appendLine("path:      ${vFile.path}")
            appendLine("kind:      ${if (vFile.isDirectory) NodeKind.directory else NodeKind.file}")
            appendLine("stableId:  ${vFile.stableId}")
            appendLine("revid:     ${vFile.revid}")
            appendLine("length:    ${vFile.cachedContent?.size ?: "not loaded"}")
            appendLine("writable:  ${vFile.isWritable}")
            appendLine("contentModel: ${vFile.contentModel ?: "—"}")
            appendLine("quality:   ${vFile.qualityLevel ?: "—"}")
            appendLine("dirty:     ${vFile.dirty}")
            appendLine("pageImage: ${vFile.hasPageImage}")
            appendLine("placeholder: ${vFile.placeholder}")
        }
    }

    private fun refreshTreePreservingState(
        tree: Tree,
        structureModel: StructureTreeModel<WikisourceTreeStructure>,
        fs: WtVirtualFileSystem?,
    ) {
        val state = TreeState.createOn(tree)

        ApplicationManager.getApplication().executeOnPooledThread {
            fs?.refresh(false)

            // AsyncTreeModel already preserves expansion for elements that
            // survive the invalidation; TreeState covers the rest (selection,
            // paths whose nodes were dropped and re-listed). applyTo drives a
            // TreeVisitor that awaits background child loading level by level.
            structureModel.invalidateAsync().thenRun {
                SwingUtilities.invokeLater { state.applyTo(tree) }
            }
        }
    }

    private companion object {
        /** Structure element behind a rendered tree node, if any. */
        private fun elementOf(node: Any?): Any? {
            val userObject = TreeUtil.getUserObject(node)
            return (userObject as? NodeDescriptor<*>)?.element ?: userObject
        }

        /**
         * Tree-display-only shorthand. `getName()`/`getPath()` on the underlying
         * [WtVirtualFile] are untouched - this never leaves the tool window.
         */
        private fun displayLabel(name: String): String =
            if (name.startsWith("Page:") && '/' in name) "Page/${name.substringAfterLast('/')}" else name

        /** VCS-modified-style blue for files with uncommitted local edits. */
        private val DIRTY_ATTRIBUTES =
            SimpleTextAttributes(SimpleTextAttributes.STYLE_PLAIN, JBColor(0x0057D8, 0x589DF6))

        /** ProofreadPage pagelist status colours, light/dark theme pairs. */
        private fun qualityColor(level: Int): JBColor = when (level) {
            0 -> JBColor(0x888888, 0x999999) // without text
            1 -> JBColor(0xD65C5C, 0xE57373) // not proofread
            2 -> JBColor(0x8E6BC7, 0x9575CD) // problematic
            3 -> JBColor(0xC7A500, 0xE0C341) // proofread
            4 -> JBColor(0x2E7D32, 0x66BB6A) // validated
            else -> JBColor.GRAY
        }
    }
}
