package org.limepepper.lang.wikitext.vfs.backend

/**
 * Abstraction over the wtbot FastAPI VFS endpoints.
 * Implementations: [HttpVfsBackend] (real), [FakeVfsBackend] (tests/offline).
 */
interface VfsBackend {
    /** Returns stat for any path; [StatResult.exists] is false for unknown paths. */
    fun stat(path: String): StatResult

    /** Batched [stat] for many paths in one round trip; result order matches [paths]. */
    fun statBulk(paths: List<String>): List<StatResult>

    /** Lists the children of a directory path. */
    fun listChildren(path: String): ListChildrenResult

    /** Reads raw content of a file path. */
    fun readContent(path: String): ContentResult

    /**
     * Writes the full new content of a file path, replacing its body.
     * [baseRevid] is the revid the edit started from — a server-side mismatch
     * against the current cached revid comes back as [WriteStatus.conflict],
     * not an exception.
     */
    fun writeContent(
        path: String,
        contentBase64: String,
        baseRevid: Long?,
        comment: String? = null,
    ): WriteResult

    /**
     * Renders an unsaved [wikitext] body to HTML via the wiki's `action=parse`
     * (live-preview semantics). Pass [path] for wikisource:// files so the
     * sidecar resolves the site/title/content-model; pass [title] alone for
     * local scratch files (parsed against the sidecar's first configured site).
     */
    fun renderPreview(path: String?, title: String?, wikitext: String): PreviewResult

    /**
     * Navigation metadata for a ProofreadPage Page: leaf — its page number,
     * position within the index, and the previous/next sibling paths that
     * the editor's page back/forward actions open. Throws
     * [VfsBackendException] when [path] is not a proofread page.
     */
    fun pageNav(path: String): PageNavResult

    /**
     * URL of the reference scan image for a ProofreadPage Page: — the source
     * the transcription is being proofread against. Building the URL is local
     * and cheap; the image itself is fetched by whoever renders it (JCEF).
     * Currently the sidecar serves a placeholder (see /preview/page-image).
     */
    fun pageImageUrl(path: String?, title: String?): String

    /** Scan annotations (bounding boxes) for a Page: leaf. */
    fun listAnnotations(path: String): List<PageAnnotation>

    /** Upserts one annotation's geometry, label, and category. */
    fun saveAnnotation(path: String, annotation: PageAnnotation): PageAnnotation

    /** Deletes an annotation and its text anchor. Unknown ids are an error. */
    fun deleteAnnotation(path: String, annotationId: String)

    /** Text anchors for a Page: leaf — the other half of the annotations. */
    fun listTextAnchors(path: String): List<PageTextAnchor>

    /** Upserts the text anchor joined to [PageTextAnchor.annotationId]. */
    fun saveTextAnchor(path: String, anchor: PageTextAnchor): PageTextAnchor

    /** Deletes just the text anchor, leaving any box. Unknown ids are an error. */
    fun deleteTextAnchor(path: String, annotationId: String)

    /** Box→range links for a Page: leaf (see [PageBoxLink]). */
    fun listBoxLinks(path: String): List<PageBoxLink>

    /**
     * Upserts the link for [PageBoxLink.boxId], repointing an existing one.
     * The target range must exist server-side; a missing range is an error.
     */
    fun saveBoxLink(path: String, link: PageBoxLink): PageBoxLink

    /** Deletes the box's link, leaving box and range. Unknown ids are an error. */
    fun deleteBoxLink(path: String, boxId: String)

    /** The enabled OCR backends configured for a Page: leaf's site. */
    fun listOcrBackends(path: String): List<OcrBackendInfo>

    /**
     * The engines and languages [backend] (default: the site's first)
     * offers — what the "Run OCR" menu's favourites are chosen from. The
     * sidecar caches this; a failure arrives as [OcrCatalog.error] rather
     * than an exception. Blocking; call off the EDT.
     */
    fun listOcrModels(path: String, backend: String? = null): OcrCatalog

    /**
     * Runs one OCR recognition for [path] through the sidecar's wrapper —
     * the sidecar picks the backend (named in [request] or the site's
     * first), translates the image reference to a backend-reachable URL,
     * and forwards the cropped segment/prompt for backends that take them.
     * Blocking; call off the EDT.
     */
    fun runOcr(path: String, request: OcrRunRequest): OcrRunResult
}
