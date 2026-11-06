package org.limepepper.lang.wikitext.tool

import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.Messages
import org.limepepper.lang.wikitext.editor.prp.PageQuality
import org.limepepper.lang.wikitext.editor.prp.PageQualityEdit
import org.limepepper.lang.wikitext.vfs.WtPaths
import org.limepepper.lang.wikitext.vfs.WtWikiFiles
import org.limepepper.lang.wikitext.vfs.WtManagedBackendFileSystem
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WriteStatus
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.util.Base64

/**
 * Sets the ProofreadPage quality level on every selected proofread page.
 *
 * Each page is a read-modify-write through the ordinary VFS `write`, so the
 * change lands in the edit journal like any other save (dirty until committed)
 * and a `baseRevid` conflict skips that page instead of overwriting it. Pages
 * with unsaved edits in an open editor are skipped too: writing underneath
 * them would only produce a conflict on their next save.
 *
 * @param level fixed level to set, or `null` to ask.
 */
internal class SetPageQualityAction(
    private val project: Project,
    private val refresh: () -> Unit,
    private val selection: () -> List<WikiBrowserNode>,
    private val level: Int? = null,
    text: String = "Set Page Quality…",
) : AnAction(text) {

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT

    override fun update(e: AnActionEvent) {
        e.presentation.isEnabledAndVisible = targets().isNotEmpty()
    }

    override fun actionPerformed(e: AnActionEvent) {
        val files = targets()
        if (files.isEmpty()) return
        val chosen = level ?: askLevel(files.size) ?: return
        ApplicationManager.getApplication().executeOnPooledThread {
            val report = files.map { setLevel(it, chosen) }
            ApplicationManager.getApplication().invokeLater { refresh(); showReport(chosen, report) }
        }
    }

    /** The `@wikitext` file of every selected proofread page, once each. */
    private fun targets(): List<String> =
        selection().mapNotNull { node ->
            if (node.contentModel != "proofread-page") return@mapNotNull null
            when {
                !node.isDirectory -> node.path.takeIf { WtPaths.aspectOf(it) == WtPaths.WIKITEXT }
                WtPaths.WIKITEXT in node.aspects ->
                    WtPaths.aspectPath(node.path, WtPaths.WIKITEXT)
                else -> null
            }
        }.distinct()

    private fun askLevel(count: Int): Int? {
        val names = PageQuality.LEVELS.map { "$it – ${PageQuality.levelName(it)}" }.toTypedArray()
        val picked = Messages.showChooseDialog(
            project,
            "Set quality on $count page(s) to:",
            "Set Page Quality",
            null,
            names,
            names[PageQuality.PROOFREAD],
        )
        return if (picked < 0) null else picked
    }

    private data class Outcome(val path: String, val result: String, val ok: Boolean)

    private fun setLevel(path: String, level: Int): Outcome {
        val label = WtPaths.displayName(path)
        return try {
            val file = WtWikiFiles.find(path) ?: return Outcome(label, "page unavailable", false)
            val documents = FileDocumentManager.getInstance()
            if (documents.getCachedDocument(file)?.let { documents.isDocumentUnsaved(it) } == true) {
                return Outcome(label, "skipped: unsaved edits in an open editor", false)
            }
            val backend = WtVfsService.instance.backend
            // Read through the backend, not the file's cache: a stale cache
            // would write back an old body with only the level changed.
            val content = backend.readContent(file.path)
            val current = content.decodeText()
            val updated = PageQualityEdit.withLevel(current, level)
                ?: return Outcome(label, "skipped: not a recognisable proofread page", false)
            if (updated == current) return Outcome(label, "already at level $level", true)
            val encoded = Base64.getEncoder().encodeToString(updated.toByteArray(Charsets.UTF_8))
            val written = backend.writeContent(file.path, encoded, content.revid, databaseId = content.databaseId)
            when (written.status) {
                WriteStatus.ok -> {
                    (file.fileSystem as WtManagedBackendFileSystem).refreshFile(file, false)
                    Outcome(label, "set to level $level", true)
                }
                WriteStatus.conflict -> Outcome(label, "conflict: ${written.message ?: "remote revision changed"}", false)
                WriteStatus.error -> Outcome(label, "error: ${written.message ?: "unknown"}", false)
            }
        } catch (e: VfsBackendException) {
            Outcome(label, "error: ${e.message}", false)
        }
    }

    private fun showReport(level: Int, report: List<Outcome>) {
        val failed = report.filterNot { it.ok }
        val summary = "${report.size - failed.size} of ${report.size} page(s) at level $level " +
            "(${PageQuality.levelName(level)}). Changes are saved locally; commit to push them."
        if (failed.isEmpty()) {
            Messages.showInfoMessage(project, summary, "Set Page Quality")
        } else {
            val detail = failed.joinToString("\n") { "${it.path}: ${it.result}" }
            Messages.showWarningDialog(project, "$summary\n\n$detail", "Set Page Quality")
        }
    }
}
