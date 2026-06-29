package org.limepepper.lang.wikitext.vfs.backend

/**
 * Mirror of the FastAPI VFS response schemas (src-py/wtbot/api/schemas.py).
 * Plain data classes — no IntelliJ or serialization framework dependency.
 * JSON parsing is handled by [HttpVfsBackend] using minimal hand-rolled logic
 * over the stdlib JSON reader, keeping this module free of heavy deps.
 */

enum class NodeKind { file, directory }

data class StatResult(
    val path: String,
    val exists: Boolean,
    val kind: NodeKind? = null,
    val stableId: Long? = null,
    val revid: Long? = null,
    val length: Long? = null,
    val timestamp: String? = null,
    val writable: Boolean = false,
)

data class ChildNode(
    val path: String,
    val name: String,
    val kind: NodeKind,
    val stableId: Long? = null,
    val revid: Long? = null,
    val length: Long? = null,
    val timestamp: String? = null,
    val writable: Boolean = false,
)

data class ListChildrenResult(
    val parentPath: String,
    val children: List<ChildNode>,
)

data class ContentResult(
    val path: String,
    val revid: Long? = null,
    val contentBase64: String,
) {
    fun decodeContent(): ByteArray = java.util.Base64.getDecoder().decode(contentBase64)
    fun decodeText(): String = String(decodeContent(), Charsets.UTF_8)
}
