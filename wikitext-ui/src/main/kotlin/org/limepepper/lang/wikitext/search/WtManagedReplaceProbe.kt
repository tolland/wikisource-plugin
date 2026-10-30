package org.limepepper.lang.wikitext.search

import com.intellij.find.FindManager
import com.intellij.find.FindModel
import com.intellij.find.impl.FindResultUsageInfo
import com.intellij.find.replaceInProject.ReplaceInProjectManager
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.editor.Document
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Computable
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileManager
import com.intellij.openapi.actionSystem.impl.SimpleDataContext
import com.intellij.psi.PsiManager
import com.intellij.psi.search.GlobalSearchScope
import com.intellij.usages.UsageInfo2UsageAdapter
import org.limepepper.lang.wikitext.vfs.WtManagedAddress
import org.limepepper.lang.wikitext.vfs.WtVirtualFileSystem
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import org.limepepper.lang.wikitext.vfs.backend.WriteStatus
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.security.MessageDigest
import java.util.Base64

/** Live, single-page diagnostic used by docs/notebooks/managed-replace.ipynb. */
class WtManagedReplaceProbe private constructor(
    private val project: Project,
    private val backend: VfsBackend,
    private val path: String,
    private val managed: VirtualFile,
    private val legacy: VirtualFile,
    private val find: String,
    private val replacement: String,
    val before: Snapshot,
    private val retainedDocuments: ProbeDocuments,
) {
    // FileDocumentManager may release clean Documents that have no open editor.
    // Keep the exact observed Documents alive throughout this multi-cell probe.
    private data class ProbeDocuments(val managed: Document, val legacy: Document)

    data class Snapshot(
        val backend: String,
        val managedVfs: String,
        val legacyVfs: String,
        val managedDocument: String,
        val legacyDocument: String,
        val managedUnsaved: Boolean,
        val legacyUnsaved: Boolean,
        val managedWritable: Boolean,
        val backendWritable: Boolean,
        val managedFileWritable: Boolean,
        val managedFsReadOnly: Boolean,
    ) {
        fun report(): String = buildString {
            fun row(label: String, text: String) {
                val hash = MessageDigest.getInstance("SHA-256").digest(text.toByteArray())
                    .joinToString("") { "%02x".format(it) }.take(12)
                appendLine("$label: chars=${text.length}, sha256=$hash")
            }
            row("backend", backend)
            row("managed VFS", managedVfs)
            row("legacy VFS", legacyVfs)
            row("managed document", managedDocument)
            row("legacy document", legacyDocument)
            appendLine("unsaved: managed=$managedUnsaved, legacy=$legacyUnsaved; managed writable=$managedWritable")
            appendLine("permissions: backend=$backendWritable, managed file=$managedFileWritable, filesystem read-only=$managedFsReadOnly")
        }
    }

    val expected: String = before.backend.replace(find, replacement)

    private fun model() = FindModel().apply {
        stringToFind = find
        stringToReplace = replacement
        isCaseSensitive = true
        isRegularExpressions = false
        isWholeWordsOnly = false
        isReplaceState = true
        isProjectScope = false
        customScope = GlobalSearchScope.fileScope(project, managed)
        isCustomScope = true
    }

    /** Opens the real dialog used by Replace in Files. Click Replace All, then inspect from the notebook. */
    fun openReplaceDialog() {
        checkBackend()
        onEdt { ReplaceInProjectManager.getInstance(project).replaceInProject(
            SimpleDataContext.getProjectContext(project), model()) }
    }

    /** Comparison path: native usage replacement plus explicit save, bypassing search/dialog enumeration. */
    fun replaceDirectly(): Int {
        checkBackend()
        return onEdt {
            val documents = FileDocumentManager.getInstance()
            val document = requireNotNull(documents.getDocument(managed))
            val finder = FindManager.getInstance(project)
            val model = model()
            val usages = ApplicationManager.getApplication().runReadAction(Computable {
                val psi = requireNotNull(PsiManager.getInstance(project).findFile(managed))
                buildList {
                    var offset = 0
                    while (offset < document.textLength) {
                        val match = finder.findString(document.charsSequence, offset, model, managed)
                        if (!match.isStringFound) break
                        add(UsageInfo2UsageAdapter(FindResultUsageInfo(finder, psi, offset, model, match)))
                        offset = match.endOffset
                    }
                }
            })
            var replaced = 0
            WriteCommandAction.runWriteCommandAction(project, "Managed VFS replacement probe", null, Runnable {
                usages.asReversed().forEach {
                    if (ReplaceInProjectManager.getInstance(project).replaceUsage(it, model, emptySet(), false)) replaced++
                }
            })
            check(document.text == expected) {
                "Native replacement did not produce expected text: matched=${usages.size}, processed=$replaced"
            }
            documents.saveDocument(document)
            replaced
        }
    }

    fun capture(): Snapshot {
        checkBackground()
        checkBackend()
        return snapshot(backend, path, managed, legacy, retainedDocuments)
    }

    fun report(after: Snapshot): String = after.report() + buildString {
        appendLine("Expected original text with '$find' replaced by '$replacement':")
        appendLine("backend=${after.backend == expected}")
        appendLine("managed VFS=${after.managedVfs == expected}")
        appendLine("managed document=${after.managedDocument == expected}")
        appendLine("legacy VFS=${after.legacyVfs == expected}")
        appendLine("legacy document=${after.legacyDocument == expected}")
        appendLine("These comparisons do not save or refresh documents.")
    }

    /** Restore via an independent backend read/write so a faulty IDE save cannot prevent cleanup. */
    fun restore(): Snapshot {
        checkBackground()
        checkBackend()
        val current = capture()
        check(!onEdt { ReplaceInProjectManager.getInstance(project).isWorkInProgress }) {
            "Replacement is still running; finish or cancel it before restoring"
        }
        check(current.backend == before.backend || current.backend == expected) {
            "Backend changed unexpectedly; refusing to overwrite it"
        }
        check(current.managedDocument in setOf(before.managedDocument, expected) &&
            current.legacyDocument in setOf(before.legacyDocument, expected)) {
            "A document changed unexpectedly; refusing to discard its edits"
        }
        if (current.backend != before.backend) {
            val latest = backend.readContent(path)
            check(latest.decodeText() == current.backend) { "Backend changed during restore" }
            val result = backend.writeContent(path,
                Base64.getEncoder().encodeToString(before.backend.toByteArray()), latest.revid)
            check(result.status == WriteStatus.ok) { "Restore failed: ${result.status}: ${result.message}" }
        }
        managed.refresh(false, false)
        legacy.fileSystem.refresh(false)
        // Prefetch off the EDT before reloading the two controlled documents.
        managed.contentsToByteArray()
        legacy.contentsToByteArray()
        onEdt { FileDocumentManager.getInstance().reloadFiles(managed, legacy) }
        return capture().also {
            check(it.backend == before.backend && it.managedDocument == before.backend &&
                it.legacyDocument == before.backend) { "Restore did not converge; inspect capture() and the IDE log" }
        }
    }

    private fun checkBackend() = check(WtVfsService.instance.backend === backend) {
        "Backend changed; create a new probe rather than writing to another backend"
    }

    companion object {
        fun prepare(project: Project, path: String, find: String, replacement: String): WtManagedReplaceProbe {
            checkBackground()
            require(find.isNotEmpty() && find != replacement)
            val backend = WtVfsService.instance.backend
            val manager = VirtualFileManager.getInstance()
            val managed = requireNotNull(manager.findFileByUrl(WtManagedAddress.fromPath(path).url))
            val legacy = requireNotNull(manager.findFileByUrl("${WtVirtualFileSystem.PROTOCOL}://$path"))
            managed.contentsToByteArray()
            legacy.contentsToByteArray()
            val retainedDocuments = onEdt {
                ApplicationManager.getApplication().runReadAction(Computable {
                    val documents = FileDocumentManager.getInstance()
                    ProbeDocuments(
                        requireNotNull(documents.getDocument(managed)),
                        requireNotNull(documents.getDocument(legacy)),
                    )
                })
            }
            val before = snapshot(backend, path, managed, legacy, retainedDocuments)
            check(!before.managedUnsaved && !before.legacyUnsaved) { "Save or discard target-page edits before preparing a probe" }
            check(before.managedWritable) {
                "Managed document is read-only. Check /vfs/stat writable and refresh cached VFS permissions.\n${before.report()}"
            }
            check(before.managedDocument == before.backend) { "Managed document already differs from backend; inspect before replacing" }
            check(find in before.backend) { "Target page does not contain '$find'; choose another search string" }
            return WtManagedReplaceProbe(project, backend, path, managed, legacy, find, replacement, before, retainedDocuments)
        }

        private fun snapshot(backend: VfsBackend, path: String,
                             managed: VirtualFile, legacy: VirtualFile, retainedDocuments: ProbeDocuments): Snapshot {
            val backendText = backend.readContent(path).decodeText()
            val backendWritable = backend.stat(path).writable
            val managedText = String(managed.contentsToByteArray(), Charsets.UTF_8)
            val legacyText = String(legacy.contentsToByteArray(), Charsets.UTF_8)
            return onEdt {
                ApplicationManager.getApplication().runReadAction(Computable {
                    val documents = FileDocumentManager.getInstance()
                    val managedDoc = retainedDocuments.managed
                    val legacyDoc = retainedDocuments.legacy
                    Snapshot(backendText, managedText, legacyText, managedDoc.text, legacyDoc.text,
                        documents.isDocumentUnsaved(managedDoc), documents.isDocumentUnsaved(legacyDoc), managedDoc.isWritable,
                        backendWritable, managed.isWritable, managed.fileSystem.isReadOnly)
                })
            }
        }

        private fun checkBackground() {
            val app = ApplicationManager.getApplication()
            check(!app.isDispatchThread && !app.isReadAccessAllowed && !app.isWriteAccessAllowed) {
                "Run this probe from a background notebook cell outside read/write actions"
            }
        }

        private fun <T> onEdt(body: () -> T): T {
            val app = ApplicationManager.getApplication()
            if (app.isDispatchThread) return body()
            check(!app.isReadAccessAllowed && !app.isWriteAccessAllowed) { "Cannot wait for EDT while holding a lock" }
            var result: Result<T>? = null
            app.invokeAndWait { result = runCatching(body) }
            return requireNotNull(result).getOrThrow()
        }
    }
}
