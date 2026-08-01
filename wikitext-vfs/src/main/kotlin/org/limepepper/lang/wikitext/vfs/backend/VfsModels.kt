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

/**
 * One OCR backend a page's site offers, from GET /ocr/backends — the
 * sidecar's wrapper over per-site OCR services (a Wikimedia OCR instance,
 * a token-guarded vision API, …). [supportsSegment] backends receive the
 * cropped bounding-box bytes; URL-driven backends have the sidecar pass
 * the wiki-side image URL instead. [supportsPrompt] backends accept a
 * custom prompt (e.g. LaTeX instructions for idiosyncratic typesetting),
 * with [defaultPrompt] as the server-side fallback.
 */
data class OcrBackendInfo(
    val name: String,
    val kind: String,
    val defaultEngine: String? = null,
    val defaultLangs: List<String> = emptyList(),
    val defaultPrompt: String? = null,
    val supportsPrompt: Boolean = false,
    val supportsSegment: Boolean = false,
    /** Whether GET /pages/ocr/models can enumerate this backend's engines. */
    val supportsDiscovery: Boolean = false,
)

/** One recognizable language/model of an engine, e.g. `en` / "English". */
data class OcrModelInfo(
    val code: String,
    val title: String,
) {
    /** "English (en)" — what a picker shows; codes alone are unreadable. */
    val displayName: String get() = if (title.isBlank()) code else "$title ($code)"
}

/**
 * One engine an OCR backend offers and the models it recognizes. An empty
 * [models] is normal rather than a failure: pix2tex reads mathematical
 * notation and has no language dimension at all.
 */
data class OcrEngineInfo(
    val engine: String,
    val models: List<OcrModelInfo> = emptyList(),
)

/**
 * What one backend can be asked for, from GET /pages/ocr/models — the
 * source the "Run OCR" menu's favourites are picked from. Far too big to
 * put in a menu directly (Google Vision alone declares hundreds of
 * languages), which is the whole reason favourites exist.
 *
 * [error] non-null means discovery failed and [engines] is empty; the
 * backend is still runnable with its configured defaults, so callers show
 * the message rather than dropping the backend.
 */
data class OcrCatalog(
    val backend: String,
    val engines: List<OcrEngineInfo> = emptyList(),
    val error: String? = null,
) {
    fun engine(name: String): OcrEngineInfo? = engines.find { it.engine == name }

    companion object {
        val EMPTY = OcrCatalog(backend = "")
    }
}

/**
 * One recognition request for POST /ocr/run. Everything is optional: the
 * sidecar fills engine/langs/prompt from the backend's configured defaults
 * and resolves the backend-reachable image URL from the page itself — the
 * client never sends its localhost rendition URL. [imageBase64] is the
 * cropped bounding-box segment (PNG) for byte-capable backends;
 * [annotationId]/geometry ride along as provenance.
 */
data class OcrRunRequest(
    val backend: String? = null,
    val annotationId: String? = null,
    val boxX: Double? = null,
    val boxY: Double? = null,
    val boxWidth: Double? = null,
    val boxHeight: Double? = null,
    val imageBase64: String? = null,
    val engine: String? = null,
    val langs: List<String>? = null,
    val prompt: String? = null,
    /** Degrees clockwise, applied by the backend after the crop. */
    val rotate: Int = 0,
)

/**
 * The recognized text from POST /ocr/run. Text travels base64-encoded
 * (multi-line; [JsonReader] does not unescape JSON strings — same
 * convention as [PreviewResult]).
 */
data class OcrRunResult(
    val backend: String,
    val kind: String,
    val engine: String? = null,
    val textBase64: String,
) {
    fun decodeText(): String =
        String(java.util.Base64.getDecoder().decode(textBase64), Charsets.UTF_8)
}
