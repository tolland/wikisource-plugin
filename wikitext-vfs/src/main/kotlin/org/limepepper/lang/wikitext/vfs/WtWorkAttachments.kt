package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.openapi.application.ApplicationManager
import com.intellij.util.xmlb.annotations.XCollection
import com.intellij.util.messages.Topic
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.io.IOException
import java.util.UUID

/** A project association and its last confirmed membership, never an alternate file identity. */
data class WtAttachedWork(
    val id: String,
    val connection: String?,
    val databaseId: String?,
    val index: WtManagedAddress,
    val content: List<WtManagedAddress>,
) {
    val name: String get() = index.backendPath.substringAfter("/Index/")
}

/** No HTTP during state loading or tree construction. Explicit attach/refresh run off the EDT. */
@Service(Service.Level.PROJECT)
@State(name = "WtWorkAttachments", storages = [Storage("wikisource-works.xml")])
class WtWorkAttachments : PersistentStateComponent<WtWorkAttachments.State> {
    class State {
        @XCollection(style = XCollection.Style.v2)
        var works: MutableList<WorkState> = mutableListOf()
    }

    class WorkState {
        var id: String = ""
        var connection: String? = null
        var databaseId: String? = null
        var indexUrl: String = ""
        @XCollection(style = XCollection.Style.v2)
        var contentUrls: MutableList<String> = mutableListOf()
    }

    private var works = emptyList<WtAttachedWork>()

    @Synchronized
    fun attachments(): List<WtAttachedWork> = works.toList()

    @Synchronized
    override fun getState(): State = State().also { state ->
        state.works = works.map { work ->
            WorkState().also {
                it.id = work.id
                it.connection = work.connection
                it.databaseId = work.databaseId
                it.indexUrl = work.index.url
                it.contentUrls = work.content.map { address -> address.url }.toMutableList()
            }
        }.toMutableList()
    }

    @Synchronized
    override fun loadState(state: State) {
        works = state.works.map { stored ->
            WtAttachedWork(stored.id, stored.connection, stored.databaseId,
                WtManagedAddress.fromUrl(stored.indexUrl),
                stored.contentUrls.map(WtManagedAddress::fromUrl))
        }.distinctBy { it.id }
        changed()
    }

    fun attach(seed: WtManagedAddress, backend: VfsBackend = WtVfsService.instance.backend): WtAttachedWork {
        val discovered = discoverManagedWork(backend, seed)
        synchronized(this) {
            val previous = works.find { it.connection == backend.cacheIdentity && it.index == discovered.index }
            if (previous != null && previous.databaseId != discovered.databaseId)
                throw IOException("Work belongs to a different database; detach and attach it explicitly")
            val attached = WtAttachedWork(previous?.id ?: UUID.randomUUID().toString(),
                backend.cacheIdentity, discovered.databaseId, discovered.index, discovered.content)
            works = works.filterNot { it.id == attached.id } + attached
            changed()
            return attached
        }
    }

    /** Failure keeps the last confirmed snapshot; detach during a request cannot reattach it. */
    fun refresh(id: String, backend: VfsBackend = WtVfsService.instance.backend): WtAttachedWork {
        val previous = attachments().find { it.id == id } ?: throw IOException("Work is detached")
        checkConnection(previous, backend)
        val discovered = discoverManagedWork(backend, previous.index)
        if (discovered.databaseId != previous.databaseId) throw IOException("Work belongs to a different database; detach and attach it explicitly")
        synchronized(this) {
            if (works.find { it.id == id } !== previous) throw IOException("Work changed during refresh; try again")
            val refreshed = previous.copy(content = discovered.content)
            works = works.map { if (it.id == id) refreshed else it }
            changed()
            return refreshed
        }
    }

    /** Validate before opening a persisted member against the currently selected backend. */
    fun checkAvailable(work: WtAttachedWork, backend: VfsBackend = WtVfsService.instance.backend) {
        checkConnection(work, backend)
        val stat = backend.stat(WtPaths.aspectPath(work.index.backendPath, WtPaths.WIKITEXT))
        if (!stat.exists) throw IOException("Attached Index is unavailable")
        if (stat.databaseId != work.databaseId) throw IOException("Work belongs to a different database; detach and attach it explicitly")
    }

    private fun checkConnection(work: WtAttachedWork, backend: VfsBackend) {
        if (work.connection != backend.cacheIdentity) throw IOException("Work belongs to a different backend connection")
    }

    /** Association only: do not delete VFS records, close tabs, or save/discard documents. */
    @Synchronized
    fun detach(id: String) {
        works = works.filterNot { it.id == id }
        changed()
    }

    private fun changed() {
        ApplicationManager.getApplication()?.takeUnless { it.isDisposed }
            ?.messageBus?.syncPublisher(CHANGED)?.attachmentsChanged(this)
    }

    companion object {
        val CHANGED = Topic.create("WtWorkAttachmentsChanged", WtWorkAttachmentsListener::class.java)
    }
}

fun interface WtWorkAttachmentsListener {
    fun attachmentsChanged(source: WtWorkAttachments)
}
