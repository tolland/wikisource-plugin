package org.limepepper.lang.wikitext.vfs.backend

import java.awt.Color
import java.awt.image.BufferedImage
import java.io.ByteArrayOutputStream
import java.util.Base64
import javax.imageio.ImageIO

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
    // page path → annotation id → annotation, in insertion order
    private val annotations = mutableMapOf<String, LinkedHashMap<String, PageAnnotation>>()
    // page path → annotation id → text anchor, independent of the boxes
    private val textAnchors = mutableMapOf<String, LinkedHashMap<String, PageTextAnchor>>()
    // page path → box id → link, one per box; dies with either endpoint
    private val boxLinks = mutableMapOf<String, LinkedHashMap<String, PageBoxLink>>()

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

    override fun pageNav(path: String): PageNavResult {
        val e = entries[path]
        if (e == null || e.kind != NodeKind.file) {
            throw VfsBackendException("not a proofread page: $path")
        }
        val parentPath = childrenOf.entries.firstOrNull { path in it.value }?.key
            ?: throw VfsBackendException("not a proofread page: $path")
        // Registration order stands in for the real backend's page_number sort.
        val siblings = childrenOf[parentPath].orEmpty()
            .mapNotNull { entries[it] }
            .filter { it.kind == NodeKind.file }
        val pos = siblings.indexOfFirst { it.path == path }
        fun entryOf(s: Entry?): PageNavEntry? = s?.let { PageNavEntry(it.path, it.name) }
        val indexPath = parentPath.removeSuffix("/Pages")
        return PageNavResult(
            current = PageNavEntry(e.path, e.name),
            indexPath = indexPath,
            indexTitle = indexPath.substringAfterLast('/'),
            pageCount = siblings.size,
            position = pos + 1,
            total = siblings.size,
            prev = entryOf(siblings.getOrNull(pos - 1)),
            next = entryOf(siblings.getOrNull(pos + 1)),
        )
    }

    override fun listAnnotations(path: String): List<PageAnnotation> =
        annotations[path].orEmpty().values.toList()

    override fun saveAnnotation(path: String, annotation: PageAnnotation): PageAnnotation {
        annotations.getOrPut(path) { LinkedHashMap() }[annotation.id] = annotation
        return annotation
    }

    override fun deleteAnnotation(path: String, annotationId: String) {
        val boxRemoved = annotations[path]?.remove(annotationId) != null
        val anchorRemoved = textAnchors[path]?.remove(annotationId) != null
        boxLinks[path]?.remove(annotationId)
        if (anchorRemoved) {
            boxLinks[path]?.values?.removeIf { it.rangeId == annotationId }
        }
        if (!boxRemoved && !anchorRemoved) {
            throw VfsBackendException("no annotation $annotationId at $path")
        }
    }

    override fun listTextAnchors(path: String): List<PageTextAnchor> =
        textAnchors[path].orEmpty().values.toList()

    override fun saveTextAnchor(path: String, anchor: PageTextAnchor): PageTextAnchor {
        textAnchors.getOrPut(path) { LinkedHashMap() }[anchor.annotationId] = anchor
        return anchor
    }

    override fun deleteTextAnchor(path: String, annotationId: String) {
        if (textAnchors[path]?.remove(annotationId) == null) {
            throw VfsBackendException("no text anchor $annotationId at $path")
        }
        boxLinks[path]?.values?.removeIf { it.rangeId == annotationId }
    }

    override fun listBoxLinks(path: String): List<PageBoxLink> =
        boxLinks[path].orEmpty().values.toList()

    override fun saveBoxLink(path: String, link: PageBoxLink): PageBoxLink {
        if (textAnchors[path]?.containsKey(link.rangeId) != true) {
            throw VfsBackendException("no text anchor ${link.rangeId} at $path to link to")
        }
        boxLinks.getOrPut(path) { LinkedHashMap() }[link.boxId] = link
        return link
    }

    override fun deleteBoxLink(path: String, boxId: String) {
        if (boxLinks[path]?.remove(boxId) == null) {
            throw VfsBackendException("no box link $boxId at $path")
        }
    }

    /** Backends advertised by [listOcrBackends]; tests/demos seed this. */
    val ocrBackends = mutableListOf(
        OcrBackendInfo(
            name = "fake-ocr",
            kind = "wikimedia",
            defaultEngine = "tesseract",
            supportsDiscovery = true,
        ),
    )

    /**
     * Engines/models advertised by [listOcrModels], keyed by backend name.
     * Seeded with the shape a real py-ocrapi instance has — several text
     * engines plus a language-less LaTeX one — because that mix is exactly
     * what the favourites menu exists to sort out.
     */
    val ocrEngines = mutableMapOf(
        "fake-ocr" to mutableListOf(
            OcrEngineInfo(
                engine = "tesseract",
                models = listOf(
                    OcrModelInfo("en", "English"),
                    OcrModelInfo("de", "German"),
                    OcrModelInfo("fr", "French"),
                ),
            ),
            OcrEngineInfo(
                engine = "google",
                models = listOf(OcrModelInfo("en", "English"), OcrModelInfo("la", "Latin")),
            ),
            OcrEngineInfo(engine = "pix2tex"),
        ),
    )

    /** Set to make [listOcrModels] report a discovery failure. */
    var ocrCatalogError: String? = null

    /** Requests [runOcr] received, newest last — for asserting in tests. */
    val ocrRequests = mutableListOf<Pair<String, OcrRunRequest>>()

    override fun listOcrBackends(path: String): List<OcrBackendInfo> = ocrBackends.toList()

    override fun listOcrModels(path: String, backend: String?): OcrCatalog {
        val info = backend?.let { name ->
            ocrBackends.find { it.name == name }
                ?: throw VfsBackendException("no OCR backend $name")
        } ?: ocrBackends.firstOrNull()
        ?: throw VfsBackendException("no OCR backend configured")
        // Discovery failure is data, not an exception — the backend stays
        // runnable on its configured defaults (see [OcrCatalog.error]).
        ocrCatalogError?.let { return OcrCatalog(backend = info.name, error = it) }
        return OcrCatalog(
            backend = info.name,
            engines = ocrEngines[info.name].orEmpty().toList(),
        )
    }

    override fun runOcr(path: String, request: OcrRunRequest): OcrRunResult {
        val backend = request.backend?.let { name ->
            ocrBackends.find { it.name == name }
                ?: throw VfsBackendException("no OCR backend $name")
        } ?: ocrBackends.firstOrNull()
        ?: throw VfsBackendException("no OCR backend configured")
        ocrRequests += path to request
        val text = "OCR of ${request.annotationId ?: path}"
        return OcrRunResult(
            backend = backend.name,
            kind = backend.kind,
            engine = request.engine ?: backend.defaultEngine,
            textBase64 = java.util.Base64.getEncoder().encodeToString(text.toByteArray()),
        )
    }

    override fun fetchReferenceImage(path: String?, title: String?, width: Int?): ByteArray {
        // PNG rather than SVG: the scan viewer decodes with ImageIO, which
        // has no SVG support.
        val image = BufferedImage(800, 1200, BufferedImage.TYPE_INT_RGB)
        image.createGraphics().apply {
            color = Color(0xF8, 0xF4, 0xE8)
            fillRect(0, 0, image.width, image.height)
            color = Color.GRAY
            drawString("fake page scan${title?.let { ": $it" } ?: ""}", 40, 60)
            dispose()
        }
        return ByteArrayOutputStream().also { ImageIO.write(image, "png", it) }.toByteArray()
    }
}
