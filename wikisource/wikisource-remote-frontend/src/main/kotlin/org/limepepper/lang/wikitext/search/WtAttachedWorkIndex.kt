package org.limepepper.lang.wikitext.search

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.Service
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.project.RootsChangeRescanningInfo
import com.intellij.openapi.module.Module
import com.intellij.openapi.roots.ex.ProjectRootManagerEx
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.vfs.VirtualFileManager
import com.intellij.openapi.vfs.VirtualFileWithId
import com.intellij.openapi.vfs.newvfs.BulkFileListener
import com.intellij.openapi.vfs.newvfs.events.VFileEvent
import com.intellij.util.indexing.IndexableSetContributorModificationTracker
import com.intellij.psi.search.GlobalSearchScope
import org.limepepper.lang.wikitext.vfs.*
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import org.limepepper.lang.wikitext.vfs.backend.WtBackendSwitchedListener
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.io.IOException
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicLong

/** Resolves eligible leaves in the background. Index and scope callbacks only read snapshots. */
@Service(Service.Level.PROJECT)
class WtAttachedWorkIndex(private val project: Project) : Disposable {
    internal data class IndexedWork(val work: WtAttachedWork, val files: Set<VirtualFile>)
    private data class Snapshot(val backend: VfsBackend, val attachments: List<WtAttachedWork>, val works: List<IndexedWork>)
    @Volatile private var snapshot: Snapshot? = null
    @Volatile private var memberPaths = emptySet<String>()
    private val requested = AtomicLong()
    private val running = AtomicBoolean()
    private val disposed = AtomicBoolean()
    private val attachments get() = project.getService(WtWorkAttachments::class.java)

    init {
        val connection = ApplicationManager.getApplication().messageBus.connect(this)
        connection.subscribe(WtWorkAttachments.CHANGED, WtWorkAttachmentsListener { source ->
            if (source === project.getServiceIfCreated(WtWorkAttachments::class.java)) requestRefresh()
        })
        connection.subscribe(WtVfsService.BACKEND_SWITCHED, WtBackendSwitchedListener { requestRefresh() })
        connection.subscribe(VirtualFileManager.VFS_CHANGES, object : BulkFileListener {
            override fun after(events: List<VFileEvent>) {
                if (events.any { it.fileSystem is WtManagedBackendFileSystem && it.path in memberPaths }) requestRefresh()
            }
        })
        requestRefresh()
    }

    /** No HTTP and no content reads, including while the scope chooser runs on the EDT. */
    internal fun cachedWorks(): List<IndexedWork> {
        val current = snapshot
        if (current == null || current.backend !== WtVfsService.instance.backend || current.attachments != attachments.attachments()) {
            if (!running.get()) requestRefresh()
            return emptyList()
        }
        return current.works.map { it.copy(files = it.files.filterTo(linkedSetOf()) { file -> file.isValid }) }
    }

    fun files(): Array<VirtualFile> = cachedWorks().flatMap { it.files }.distinct().toTypedArray()

    fun scopes(): Array<GlobalSearchScope> = cachedWorks().map { indexed ->
        val name = "Wikisource: ${indexed.work.name}"
        if (indexed.files.isNotEmpty()) GlobalSearchScope.filesScope(project, indexed.files, name)
        else object : GlobalSearchScope(project) {
            override fun getDisplayName(): String = "$name (no indexed content)"
            override fun contains(file: VirtualFile): Boolean = false
            override fun isSearchInModuleContent(module: Module): Boolean = false
            override fun isSearchInLibraries(): Boolean = false
        }
    }.toTypedArray()

    fun requestRefresh() {
        requested.incrementAndGet()
        schedule()
    }

    private fun schedule() {
        if (disposed.get() || project.isDisposed || !running.compareAndSet(false, true)) return
        ApplicationManager.getApplication().executeOnPooledThread {
            var processed = -1L
            try {
                do {
                    processed = requested.get()
                    rebuild()
                } while (!disposed.get() && !project.isDisposed && processed != requested.get())
            } finally {
                running.set(false)
                if (processed != requested.get()) schedule()
            }
        }
    }

    private fun rebuild() {
        if (disposed.get() || project.isDisposed) return
        val backend = WtVfsService.instance.backend
        val attached = attachments.attachments()
        memberPaths = attached.flatMap { it.content }.mapTo(hashSetOf()) { it.backendPath }
        val resolved = attached.map { work ->
            ProgressManager.checkCanceled()
            val files = try {
                indexableWorkContent(backend, work).mapTo(linkedSetOf()) { address ->
                    ProgressManager.checkCanceled()
                    val file = WtWikiFiles.find(address.backendPath) ?: throw IOException("Cannot resolve ${address.url}")
                    if (file !is VirtualFileWithId || file.id <= 0 || file.isDirectory || !file.isValid)
                        throw IOException("Not a managed content file: ${address.url}")
                    file
                }
            } catch (failure: IOException) {
                Logger.getInstance(javaClass).info("Attached work unavailable for indexing: ${work.name}: ${failure.message}")
                emptySet()
            }
            IndexedWork(work, files)
        }
        if (disposed.get() || project.isDisposed) return
        if (backend !== WtVfsService.instance.backend || attached != attachments.attachments()) {
            requested.incrementAndGet()
            return
        }
        val previousFiles = snapshot?.works?.flatMap { it.files }?.toSet().orEmpty()
        snapshot = Snapshot(backend, attached, resolved)
        val currentFiles = resolved.flatMap { it.files }.toSet()
        if (previousFiles != currentFiles) notifyRootsChanged()
    }

    /** Recompute contributor origins, without asking IntelliJ to scan the database or every project root. */
    @Suppress("UnstableApiUsage")
    private fun notifyRootsChanged() {
        ApplicationManager.getApplication().invokeLater {
            if (!disposed.get() && !project.isDisposed) ApplicationManager.getApplication().runWriteAction {
                IndexableSetContributorModificationTracker.getInstance().incModificationCount()
                ProjectRootManagerEx.getInstanceEx(project).makeRootsChange({}, RootsChangeRescanningInfo.RESCAN_DEPENDENCIES_IF_NEEDED)
            }
        }
    }

    override fun dispose() { disposed.set(true) }
}
