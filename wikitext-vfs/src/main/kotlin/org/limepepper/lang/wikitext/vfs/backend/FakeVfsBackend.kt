package org.limepepper.lang.wikitext.vfs.backend

import java.util.Base64

/**
 * In-memory [VfsBackend] for tests and offline use.
 * Populated via [addFile] / [addDirectory] before use.
 */
class FakeVfsBackend : VfsBackend {

    private data class Entry(
        val path: String,
        val name: String,
        val kind: NodeKind,
        var content: ByteArray = ByteArray(0),
        val stableId: Long? = null,
        var revid: Long? = null,
        val contentModel: String? = null,
    )

    private val entries = mutableMapOf<String, Entry>()
    // explicit parent path → ordered list of child paths
    private val childrenOf = mutableMapOf<String, MutableList<String>>()

    /**
     * Register a directory. The parent is the longest already-registered
     * directory path that is a strict prefix of [path].
     */
    fun addDirectory(path: String, name: String = path.substringAfterLast('/'), stableId: Long? = null): FakeVfsBackend {
        entries[path] = Entry(path, name, NodeKind.directory, stableId = stableId)
        _registerWithParent(path)
        return this
    }

    /**
     * Register a file. [name] is the display name (may differ from the last
     * path segment when titles contain '/').
     */
    fun addFile(
        path: String,
        content: String,
        name: String = path.substringAfterLast('/'),
        stableId: Long? = null,
        revid: Long? = null,
        contentModel: String? = null,
    ): FakeVfsBackend {
        entries[path] = Entry(path, name, NodeKind.file, content.toByteArray(), stableId, revid, contentModel)
        _registerWithParent(path)
        return this
    }

    private fun _registerWithParent(path: String) {
        // Find the longest registered directory that is a strict prefix of path
        val parent = entries.values
            .filter { it.kind == NodeKind.directory && path.startsWith(it.path + "/") }
            .maxByOrNull { it.path.length }
            ?: return  // root-level entry, no parent to register under
        childrenOf.getOrPut(parent.path) { mutableListOf() }.add(path)
    }

    override fun stat(path: String): StatResult {
        val e = entries[path] ?: return StatResult(path = path, exists = false)
        return StatResult(
            path = path,
            exists = true,
            name = e.name,
            kind = e.kind,
            stableId = e.stableId,
            revid = e.revid,
            length = if (e.kind == NodeKind.file) e.content.size.toLong() else null,
            contentModel = e.contentModel,
        )
    }

    override fun statBulk(paths: List<String>): List<StatResult> = paths.map(::stat)

    override fun listChildren(path: String): ListChildrenResult {
        val children = childrenOf[path].orEmpty().mapNotNull { childPath ->
            val e = entries[childPath] ?: return@mapNotNull null
            ChildNode(
                path = e.path,
                name = e.name,
                kind = e.kind,
                stableId = e.stableId,
                revid = e.revid,
                length = if (e.kind == NodeKind.file) e.content.size.toLong() else null,
                contentModel = e.contentModel,
            )
        }
        return ListChildrenResult(parentPath = path, children = children)
    }

    override fun readContent(path: String): ContentResult {
        val e = entries[path] ?: throw VfsBackendException("not found: $path")
        return ContentResult(
            path = path,
            revid = e.revid,
            contentBase64 = Base64.getEncoder().encodeToString(e.content),
        )
    }

    override fun writeContent(
        path: String,
        contentBase64: String,
        baseRevid: Long?,
        comment: String?,
    ): WriteResult {
        val e = entries[path] ?: return WriteResult(path, WriteStatus.error, message = "not found: $path")
        if (baseRevid != null && e.revid != null && baseRevid != e.revid) {
            return WriteResult(path, WriteStatus.conflict, newRevid = e.revid, message = "edit conflict")
        }
        e.content = Base64.getDecoder().decode(contentBase64)
        e.revid = (e.revid ?: 0L) + 1
        return WriteResult(path, WriteStatus.ok, newRevid = e.revid)
    }

    override fun renderPreview(path: String?, title: String?, wikitext: String): PreviewResult {
        val escaped = wikitext
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        val html = "<div class=\"mw-parser-output\"><p>$escaped</p></div>"
        return PreviewResult(
            title = title ?: path?.substringAfterLast('/') ?: "Preview",
            htmlBase64 = Base64.getEncoder().encodeToString(html.toByteArray()),
        )
    }
}
