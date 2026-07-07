package org.limepepper.lang.wikitext.preview

import com.intellij.icons.AllIcons
import com.intellij.ide.ActivityTracker
import com.intellij.openapi.actionSystem.*
import com.intellij.openapi.actionSystem.ex.CustomComponentAction
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileManager
import com.intellij.ui.JBColor
import com.intellij.ui.components.JBLabel
import com.intellij.util.ui.JBUI
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.backend.PageNavEntry
import org.limepepper.lang.wikitext.vfs.backend.PageNavResult
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import javax.swing.JComponent

private val NAV_LOG = logger<WtPageNavToolbar>()

/**
 * Button row across the top of the text-editor half of the split editor,
 * installed as the editor's header component (the same slot the find bar
 * uses). Holds page navigation for the transcription workflow: back/forward
 * open the previous/next Page: of the same index, resolved once per editor
 * from the sidecar's GET /pages/nav (see [PageNavResult]).
 */
internal class WtPageNavToolbar(
    targetComponent: JComponent,
    file: VirtualFile?,
    /** Extra actions appended after a separator (e.g. the form/raw toggle). */
    trailingActions: List<AnAction> = emptyList(),
) {
    val component: JComponent

    /** Nav metadata for [file]; null until the background fetch lands (or
     * forever, when the file is not a wikisource page / the sidecar is down —
     * the actions just stay disabled). */
    @Volatile
    private var nav: PageNavResult? = null

    init {
        val group = DefaultActionGroup(
            OpenSiblingPageAction(
                "Previous Page",
                "Open the previous page of this index",
                AllIcons.Actions.Back,
            ) { nav?.prev },
            OpenSiblingPageAction(
                "Next Page",
                "Open the next page of this index",
                AllIcons.Actions.Forward,
            ) { nav?.next },
            PagePositionLabel { nav },
        )
        if (trailingActions.isNotEmpty()) {
            group.addSeparator()
            trailingActions.forEach(group::add)
        }
        val toolbar = ActionManager.getInstance()
            .createActionToolbar("WikitextPageNavToolbar", group, true)
        toolbar.targetComponent = targetComponent
        component = toolbar.component.apply {
            border = JBUI.Borders.customLineBottom(JBColor.border())
        }
        loadNav(file)
    }

    private fun loadNav(file: VirtualFile?) {
        val path = (file as? WtVirtualFile)?.path ?: return
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                nav = WtVfsService.instance.backend.pageNav(path)
                // Nudge the action subsystem so the buttons enable without
                // waiting for the next user-driven update cycle.
                ActivityTracker.getInstance().inc()
            } catch (e: VfsBackendException) {
                NAV_LOG.info("page nav unavailable for $path: ${e.message}")
            }
        }
    }
}

/**
 * Opens the prev/next sibling supplied by [target] in a new editor tab (which
 * builds its own split editor and toolbar, so nav state never goes stale).
 */
private class OpenSiblingPageAction(
    text: String,
    description: String,
    icon: javax.swing.Icon,
    private val target: () -> PageNavEntry?,
) : AnAction(text, description, icon) {

    override fun update(event: AnActionEvent) {
        event.presentation.isEnabled = event.project != null && target() != null
    }

    override fun actionPerformed(event: AnActionEvent) {
        val project = event.project ?: return
        val entry = target() ?: return
        openWikisourcePage(project, entry.path)
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

/** Non-interactive "Page N of M" indicator fed by the same nav metadata. */
private class PagePositionLabel(
    private val nav: () -> PageNavResult?,
) : AnAction(), CustomComponentAction {

    override fun createCustomComponent(presentation: Presentation, place: String): JComponent =
        JBLabel().apply { border = JBUI.Borders.empty(0, 8) }

    override fun updateCustomComponent(component: JComponent, presentation: Presentation) {
        (component as JBLabel).text = presentation.text.orEmpty()
    }

    override fun update(event: AnActionEvent) {
        val nav = nav()
        event.presentation.isVisible = nav != null
        event.presentation.text = nav?.let {
            val number = it.current.pageNumber ?: it.position
            val count = it.pageCount ?: it.total
            "Page $number of $count"
        } ?: ""
    }

    override fun actionPerformed(event: AnActionEvent) = Unit

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}

/**
 * Resolves a wikisource:// VFS [path] off the EDT (findFileByPath stats the
 * sidecar) and opens it in the front editor tab.
 */
private fun openWikisourcePage(project: Project, path: String) {
    ApplicationManager.getApplication().executeOnPooledThread {
        val fileSystem = VirtualFileManager.getInstance().getFileSystem(WtVirtualFile.PROTOCOL)
        val target = fileSystem?.findFileByPath(path)
        if (target == null) {
            NAV_LOG.warn("page nav target did not resolve: $path")
            return@executeOnPooledThread
        }
        ApplicationManager.getApplication().invokeLater {
            if (!project.isDisposed) {
                FileEditorManager.getInstance(project).openFile(target, true)
            }
        }
    }
}
