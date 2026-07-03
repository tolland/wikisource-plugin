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
    val name: String? = null,
    val kind: NodeKind? = null,
    val stableId: Long? = null,
    val revid: Long? = null,
    val length: Long? = null,
    val timestamp: String? = null,
    val writable: Boolean = false,
    /** Remote contentmodel, e.g. "proofread-index"/"proofread-page"/"wikitext". Null for dirs. */
    val contentModel: String? = null,
    /** ProofreadPage quality 0-4 for proofread-page files; drives tree colour-coding. */
    val qualityLevel: Int? = null,
    /** Uncommitted local edits (EditJournal) exist for the backing page. */
    val dirty: Boolean = false,
    /** A scan reference image is known; pixels via GET /pages/image?path=&width=. */
    val hasPageImage: Boolean = false,
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
    val contentModel: String? = null,
    val qualityLevel: Int? = null,
    val dirty: Boolean = false,
    val hasPageImage: Boolean = false,
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

enum class WriteStatus { ok, conflict, error }

/**
 * Rendered live-preview HTML from POST /preview/render — the sidecar's proxy
 * over MediaWiki's `action=parse`. HTML travels base64-encoded because
 * [JsonReader] does not unescape JSON string values.
 */
data class PreviewResult(
    val title: String,
    val htmlBase64: String,
    /** Wiki server origin, e.g. "https://en.wikisource.org" — null for fakes. */
    val server: String? = null,
    /** MediaWiki script path on [server], e.g. "/w". */
    val scriptPath: String? = null,
) {
    fun decodeHtml(): String =
        String(java.util.Base64.getDecoder().decode(htmlBase64), Charsets.UTF_8)
}

data class WriteResult(
    val path: String,
    val status: WriteStatus,
    val newRevid: Long? = null,
    val message: String? = null,
)
