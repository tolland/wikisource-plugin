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
    /** No remote revision backs this file — a missing proofread page's local stub. */
    val placeholder: Boolean = false,
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
    val placeholder: Boolean = false,
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

/** One Page: in [PageNavResult], addressed the way files are opened — by VFS path. */
data class PageNavEntry(
    val path: String,
    val title: String,
    val pageNumber: Int? = null,
)

/**
 * Page-navigation metadata for a proofread Page: leaf, from GET /pages/nav —
 * where the page sits within its index and which siblings the editor's
 * back/forward buttons should open. Sibling order matches the Pages/ listing.
 */
data class PageNavResult(
    val current: PageNavEntry,
    val indexPath: String,
    val indexTitle: String,
    /** The index's total page count (IndexMeta), when known. */
    val pageCount: Int? = null,
    /** 1-based position among the index's currently cached pages. */
    val position: Int,
    val total: Int,
    val prev: PageNavEntry? = null,
    val next: PageNavEntry? = null,
)

data class WriteResult(
    val path: String,
    val status: WriteStatus,
    val newRevid: Long? = null,
    val message: String? = null,
)

/**
 * One scan annotation from /pages/annotations — a bounding box drawn over
 * the reference image, in scan-pixel coordinates. [category] classifies the
 * region for the OCR pipeline (one of the sidecar's AnnotationCategory wire
 * values: "header", "footer", "body", "paragraph", "section", "ignore");
 * null = uncategorized. Text anchoring is a separate resource (see
 * [PageTextAnchor]) joined by [id].
 */
data class PageAnnotation(
    val id: String,
    val x: Double,
    val y: Double,
    val width: Double,
    val height: Double,
    val label: String? = null,
    val category: String? = null,
)

/**
 * One text anchor from /pages/text-anchors — a range of the transcription
 * text that is the target for OCR output or other processed text, joined to
 * its bounding box (if any) by [annotationId]. Either side may exist
 * without the other: mark the text first, or draw the box first.
 *
 * textStart == textEnd = insertion point; textStart < textEnd = replace
 * range. [anchorRevid] is the revision the offsets were computed against —
 * a mismatch with the page's current revid means the anchor is stale.
 */
data class PageTextAnchor(
    val annotationId: String,
    val textStart: Int,
    val textEnd: Int,
    val anchorRevid: Long? = null,
)

/**
 * One box→range link from /pages/box-links: the bounding box [boxId]'s
 * content is destined for the text range [rangeId]. Explicit rows replace
 * the old implicit shared-id convention — a box links to at most one range,
 * several boxes may target one range, and the link dies with either
 * endpoint (deleting the box or the range deletes it server-side).
 */
data class PageBoxLink(
    val boxId: String,
    val rangeId: String,
)
