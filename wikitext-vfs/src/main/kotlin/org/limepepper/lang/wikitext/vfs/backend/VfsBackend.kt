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

    /** Scan annotations (bounding boxes + text anchors) for a Page: leaf. */
    fun listAnnotations(path: String): AnnotationListResult

    /**
     * Upserts one rect annotation — geometry, label, and anchor together
     * (null anchor offsets unlink). The scan raster size must accompany a
     * page's first annotation: it becomes the annotation document's
     * coordinate space, and only the caller's decoded image knows it.
     * Sending it on every save is harmless.
     */
    fun saveAnnotation(
        path: String,
        annotation: PageAnnotation,
        imageWidth: Int? = null,
        imageHeight: Int? = null,
    ): PageAnnotation

    /** Deletes an annotation and its anchor. Unknown ids are an error. */
    fun deleteAnnotation(path: String, annotationId: String)
}
