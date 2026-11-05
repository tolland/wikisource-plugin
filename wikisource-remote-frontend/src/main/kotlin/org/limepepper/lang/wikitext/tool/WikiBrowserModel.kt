package org.limepepper.lang.wikitext.tool

import org.limepepper.lang.wikitext.vfs.backend.*
import java.util.concurrent.ConcurrentHashMap

/** One occurrence in the relationship tree; this is never an editable VirtualFile. */
internal class WikiBrowserNode(
    val key: Key,
    val parent: WikiBrowserNode?,
    @Volatile var state: StatResult,
) {
    data class Key(val databaseId: String?, val parent: Key?, val path: String)
    @Volatile var cachedChildren: List<WikiBrowserNode>? = null
    val path get() = state.path
    val name get() = state.name ?: path.substringAfterLast('/')
    val isDirectory get() = state.kind == NodeKind.directory
    val contentModel get() = state.contentModel
    val qualityLevel get() = state.qualityLevel
    val dirty get() = state.dirty
    val placeholder get() = state.placeholder
    val hasReferenceImage get() = state.hasReferenceImage
    val hasChildren get() = state.hasChildren
    val aspects get() = state.aspects
    override fun equals(other: Any?) = other is WikiBrowserNode && key == other.key
    override fun hashCode() = key.hashCode()
    override fun toString() = path
}

/** The API describes graph edges, including @pages; managed VFS owns editor identity. */
internal class WikiBrowserModel(private val backendProvider: () -> VfsBackend = { WtVfsService.instance.backend }) {
    private val nodes = ConcurrentHashMap<WikiBrowserNode.Key, WikiBrowserNode>()
    @Volatile private var databaseId: String? = null
    private val backend get() = backendProvider()

    fun roots(): List<WikiBrowserNode> {
        val result = backend.listChildren("/")
        if (databaseId != result.databaseId) {
            nodes.clear()
            databaseId = result.databaseId
        }
        return result.children.map { node(it.asStatResult(result.databaseId), null) }
    }

    fun children(parent: WikiBrowserNode): List<WikiBrowserNode> {
        parent.cachedChildren?.let { return it }
        val result = backend.listChildren(parent.path)
        if (result.databaseId != parent.key.databaseId) throw VfsBackendException("Database changed; refresh the browser")
        return result.children.map { node(it.asStatResult(result.databaseId), parent) }
            .also { parent.cachedChildren = it }
    }

    private fun node(state: StatResult, parent: WikiBrowserNode?): WikiBrowserNode {
        val key = WikiBrowserNode.Key(state.databaseId, parent?.key, state.path)
        return nodes.computeIfAbsent(key) { WikiBrowserNode(key, parent, state) }.also { it.state = state }
    }

    fun refresh(node: WikiBrowserNode) {
        val state = backend.stat(node.path)
        if (state.databaseId != node.key.databaseId) throw VfsBackendException("Database changed; refresh the browser")
        if (state.exists) node.state = state
        node.cachedChildren = null
    }

    fun invalidate() { nodes.values.forEach { it.cachedChildren = null } }
}
