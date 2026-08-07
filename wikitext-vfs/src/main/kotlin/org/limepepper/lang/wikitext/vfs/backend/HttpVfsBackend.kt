package org.limepepper.lang.wikitext.vfs.backend

import java.io.IOException
import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration
import java.util.UUID

/**
 * Calls the wtbot FastAPI VFS endpoints over HTTP.
 *
 * Uses only the JDK HTTP client — no extra runtime dependencies.
 * JSON is parsed with a minimal hand-rolled extractor ([JsonReader]) rather
 * than a full library so the wikitext-vfs module stays dep-light.
 *
 * Immutable once built. Pointing the plugin at a different sidecar means
 * constructing a new instance and installing it — [WtVfsService] does that in
 * response to a settings change, so that switching backends also invalidates
 * the caches filled from the old one. Mutating `baseUrl` in place would swap
 * the destination while leaving those caches silently intact.
 *
 * @param baseUrl  e.g. "http://127.0.0.1:18574" — no trailing slash
 * @param timeout  per-request timeout
 */
class HttpVfsBackend(
    private val baseUrl: String,
    private val timeout: Duration = Duration.ofSeconds(10),
    private val client: HttpClient = buildClient(timeout),
) : VfsBackend {

    companion object {
        private fun buildClient(timeout: Duration): HttpClient =
            HttpClient.newBuilder()
                .connectTimeout(timeout)
                .build()
    }

    // Expose for tests
    internal fun getBaseUrlForTesting(): String = baseUrl

    override fun stat(path: String): StatResult {
        val json = get("/vfs/stat", "path" to path)
        return JsonReader(json).run {
            StatResult(
                path = string("path"),
                exists = bool("exists"),
                name = stringOrNull("name"),
                kind = stringOrNull("kind")?.let { NodeKind.valueOf(it) },
                stableId = longOrNull("stable_id"),
                revid = longOrNull("revid"),
                length = longOrNull("length"),
                timestamp = stringOrNull("timestamp"),
                writable = boolOrDefault("writable", false),
                contentModel = stringOrNull("content_model"),
                qualityLevel = longOrNull("quality_level")?.toInt(),
                dirty = boolOrDefault("dirty", false),
                hasReferenceImage = boolOrDefault("has_reference_image", false),
                placeholder = boolOrDefault("placeholder", false),
            )
        }
    }

    override fun statBulk(paths: List<String>): List<StatResult> {
        if (paths.isEmpty()) return emptyList()
        val body = "{\"paths\":[" + paths.joinToString(",") { "\"${escapeJson(it)}\"" } + "]}"
        val json = post("/vfs/stat/bulk", body)
        return JsonReader(json).array("results") { r ->
            StatResult(
                path = r.string("path"),
                exists = r.bool("exists"),
                name = r.stringOrNull("name"),
                kind = r.stringOrNull("kind")?.let { NodeKind.valueOf(it) },
                stableId = r.longOrNull("stable_id"),
                revid = r.longOrNull("revid"),
                length = r.longOrNull("length"),
                timestamp = r.stringOrNull("timestamp"),
                writable = r.boolOrDefault("writable", false),
                contentModel = r.stringOrNull("content_model"),
                qualityLevel = r.longOrNull("quality_level")?.toInt(),
                dirty = r.boolOrDefault("dirty", false),
                hasReferenceImage = r.boolOrDefault("has_reference_image", false),
                placeholder = r.boolOrDefault("placeholder", false),
            )
        }
    }

    override fun listChildren(path: String): ListChildrenResult {
        val json = get("/vfs/children", "path" to path)
        return JsonReader(json).run {
            ListChildrenResult(
                parentPath = string("parent_path"),
                children = array("children") { child ->
                    ChildNode(
                        path = child.string("path"),
                        name = child.string("name"),
                        kind = NodeKind.valueOf(child.string("kind")),
                        stableId = child.longOrNull("stable_id"),
                        revid = child.longOrNull("revid"),
                        length = child.longOrNull("length"),
                        timestamp = child.stringOrNull("timestamp"),
                        writable = child.boolOrDefault("writable", false),
                        contentModel = child.stringOrNull("content_model"),
                        qualityLevel = child.longOrNull("quality_level")?.toInt(),
                        dirty = child.boolOrDefault("dirty", false),
                        hasReferenceImage = child.boolOrDefault("has_reference_image", false),
                        placeholder = child.boolOrDefault("placeholder", false),
                    )
                },
            )
        }
    }

    override fun readContent(path: String): ContentResult {
        val json = get("/vfs/content", "path" to path)
        return JsonReader(json).run {
            ContentResult(
                path = string("path"),
                revid = longOrNull("revid"),
                contentBase64 = string("content_base64"),
            )
        }
    }

    override fun writeContent(
        path: String,
        contentBase64: String,
        baseRevid: Long?,
        comment: String?,
    ): WriteResult {
        val body = buildJsonObject(
            "path" to path,
            "content_base64" to contentBase64,
            "base_revid" to baseRevid,
            "comment" to comment,
        )
        val json = post("/vfs/content", body)
        return JsonReader(json).run {
            WriteResult(
                path = string("path"),
                status = WriteStatus.valueOf(string("status")),
                newRevid = longOrNull("new_revid"),
                message = stringOrNull("message"),
            )
        }
    }

    override fun renderPreview(path: String?, title: String?, wikitext: String): PreviewResult {
        val body = buildJsonObject(
            "path" to path,
            "title" to title,
            "wikitext" to wikitext,
        )
        val json = post("/preview/render", body)
        return JsonReader(json).run {
            PreviewResult(
                title = string("title"),
                htmlBase64 = string("html_base64"),
                server = stringOrNull("server"),
                scriptPath = stringOrNull("script_path"),
            )
        }
    }

    override fun pageNav(path: String): PageNavResult {
        val json = get("/pages/nav", "path" to path)
        // current/prev/next carry the same field names (path/title/page_number),
        // so each is read from its own extracted sub-object — never from the
        // full response, where JsonReader's first-occurrence scan would cross
        // object boundaries.
        fun entry(r: JsonReader?): PageNavEntry? = r?.run {
            PageNavEntry(
                path = string("path"),
                title = string("title"),
                pageNumber = longOrNull("page_number")?.toInt(),
            )
        }
        return JsonReader(json).run {
            PageNavResult(
                current = entry(objectOrNull("current"))
                    ?: throw VfsBackendException("malformed /pages/nav response: no 'current'"),
                indexPath = string("index_path"),
                indexTitle = string("index_title"),
                pageCount = longOrNull("page_count")?.toInt(),
                position = longOrNull("position")?.toInt() ?: 0,
                total = longOrNull("total")?.toInt() ?: 0,
                prev = entry(objectOrNull("prev")),
                next = entry(objectOrNull("next")),
            )
        }
    }

    override fun fetchReferenceImage(path: String?, title: String?, width: Int?): ByteArray {
        val params = listOfNotNull(
            path?.let { "path" to it },
            title?.let { "title" to it },
            width?.let { "width" to it.toString() },
        )
        return getBytes("/reference-image", *params.toTypedArray())
    }

    override fun listAnnotations(path: String): List<PageAnnotation> {
        val json = get("/pages/annotations", "path" to path)
        return JsonReader(json).array("annotations", ::readAnnotation)
    }

    override fun saveAnnotation(path: String, annotation: PageAnnotation): PageAnnotation {
        val body = buildJsonObject(
            "x" to annotation.x,
            "y" to annotation.y,
            "width" to annotation.width,
            "height" to annotation.height,
            "label" to annotation.label,
            "category" to annotation.category,
        )
        val json = put(
            "/pages/annotations/${URLEncoder.encode(annotation.id, "UTF-8")}",
            body,
            "path" to path,
        )
        return readAnnotation(JsonReader(json))
    }

    override fun deleteAnnotation(path: String, annotationId: String) {
        delete(
            "/pages/annotations/${URLEncoder.encode(annotationId, "UTF-8")}",
            "path" to path,
        )
    }

    override fun listTextAnchors(path: String): List<PageTextAnchor> {
        val json = get("/pages/text-anchors", "path" to path)
        return JsonReader(json).array("anchors", ::readTextAnchor)
    }

    override fun saveTextAnchor(path: String, anchor: PageTextAnchor): PageTextAnchor {
        val body = buildJsonObject(
            "text_start" to anchor.textStart,
            "text_end" to anchor.textEnd,
            "anchor_revid" to anchor.anchorRevid,
        )
        val json = put(
            "/pages/text-anchors/${URLEncoder.encode(anchor.annotationId, "UTF-8")}",
            body,
            "path" to path,
        )
        return readTextAnchor(JsonReader(json))
    }

    override fun deleteTextAnchor(path: String, annotationId: String) {
        delete(
            "/pages/text-anchors/${URLEncoder.encode(annotationId, "UTF-8")}",
            "path" to path,
        )
    }

    override fun listBoxLinks(path: String): List<PageBoxLink> {
        val json = get("/pages/box-links", "path" to path)
        return JsonReader(json).array("links", ::readBoxLink)
    }

    override fun saveBoxLink(path: String, link: PageBoxLink): PageBoxLink {
        val body = buildJsonObject("range_annotation_id" to link.rangeId)
        val json = put(
            "/pages/box-links/${URLEncoder.encode(link.boxId, "UTF-8")}",
            body,
            "path" to path,
        )
        return readBoxLink(JsonReader(json))
    }

    override fun deleteBoxLink(path: String, boxId: String) {
        delete(
            "/pages/box-links/${URLEncoder.encode(boxId, "UTF-8")}",
            "path" to path,
        )
    }

    override fun listOcrBackends(path: String): List<OcrBackendInfo> {
        val json = get("/pages/ocr/backends", "path" to path)
        return JsonReader(json).array("backends") { r ->
            OcrBackendInfo(
                name = r.string("name"),
                kind = r.string("kind"),
                defaultEngine = r.stringOrNull("default_engine"),
                defaultLangs = r.stringArray("default_langs"),
                defaultPrompt = r.stringOrNull("default_prompt"),
                supportsPrompt = r.boolOrDefault("supports_prompt", false),
                supportsSegment = r.boolOrDefault("supports_segment", false),
                supportsDiscovery = r.boolOrDefault("supports_discovery", false),
            )
        }
    }

    override fun listOcrModels(path: String, backend: String?): OcrCatalog {
        val params = mutableListOf("path" to path)
        backend?.let { params += "backend" to it }
        val json = get("/pages/ocr/models", *params.toTypedArray())
        return JsonReader(json).run {
            OcrCatalog(
                backend = string("backend"),
                engines = array("engines") { engine ->
                    OcrEngineInfo(
                        engine = engine.string("engine"),
                        models = engine.array("models") { model ->
                            OcrModelInfo(
                                code = model.string("code"),
                                title = model.stringOrNull("title").orEmpty(),
                            )
                        },
                    )
                },
                error = stringOrNull("error"),
            )
        }
    }

    override fun runOcr(path: String, request: OcrRunRequest): OcrRunResult {
        // Hand-assembled because the body nests a box object and a string
        // array, which the flat buildJsonObject helper doesn't cover.
        val fields = mutableListOf(
            "\"path\":${jsonValue(path)}",
            "\"backend\":${jsonValue(request.backend)}",
            "\"annotation_id\":${jsonValue(request.annotationId)}",
            "\"image_base64\":${jsonValue(request.imageBase64)}",
            "\"engine\":${jsonValue(request.engine)}",
            "\"prompt\":${jsonValue(request.prompt)}",
            "\"rotate\":${request.rotate}",
        )
        request.langs?.let { langs ->
            fields += "\"langs\":[" + langs.joinToString(",") { jsonValue(it) } + "]"
        }
        if (request.boxX != null && request.boxY != null &&
            request.boxWidth != null && request.boxHeight != null
        ) {
            fields += "\"box\":{\"x\":${request.boxX},\"y\":${request.boxY}," +
                "\"width\":${request.boxWidth},\"height\":${request.boxHeight}}"
        }
        val json = post("/pages/ocr/run", fields.joinToString(",", "{", "}"))
        return JsonReader(json).run {
            OcrRunResult(
                backend = string("backend"),
                kind = string("kind"),
                engine = stringOrNull("engine"),
                textBase64 = string("text_base64"),
            )
        }
    }

    private fun readBoxLink(r: JsonReader): PageBoxLink = PageBoxLink(
        boxId = r.string("box_annotation_id"),
        rangeId = r.string("range_annotation_id"),
    )

    private fun readAnnotation(r: JsonReader): PageAnnotation = PageAnnotation(
        id = r.string("id"),
        x = r.double("x"),
        y = r.double("y"),
        width = r.double("width"),
        height = r.double("height"),
        label = r.stringOrNull("label"),
        category = r.stringOrNull("category"),
    )

    private fun readTextAnchor(r: JsonReader): PageTextAnchor = PageTextAnchor(
        annotationId = r.string("annotation_id"),
        textStart = r.longOrNull("text_start")?.toInt() ?: 0,
        textEnd = r.longOrNull("text_end")?.toInt() ?: 0,
        anchorRevid = r.longOrNull("anchor_revid"),
    )

    // -------------------------------------------------------------------------

    private fun queryUri(endpoint: String, vararg params: Pair<String, String>): URI {
        val query = params.joinToString("&") { (k, v) ->
            "${URLEncoder.encode(k, "UTF-8")}=${URLEncoder.encode(v, "UTF-8")}"
        }
        return URI.create(if (query.isEmpty()) "$baseUrl$endpoint" else "$baseUrl$endpoint?$query")
    }

    /**
     * Every request carries an X-Request-Id the sidecar echoes into its error
     * object and error-log lines, so a plugin-side failure and the matching
     * sidecar line join on one id.
     */
    private fun requestBuilder(uri: URI, requestId: String): HttpRequest.Builder =
        HttpRequest.newBuilder(uri)
            .timeout(timeout)
            .version(HttpClient.Version.HTTP_1_1) // avoid upgrade requests
            .header("X-Request-Id", requestId)

    private fun newRequestId(): String = UUID.randomUUID().toString().substringBefore('-')

    private fun get(endpoint: String, vararg params: Pair<String, String>): String {
        val uri = queryUri(endpoint, *params)
        val requestId = newRequestId()
        val req = requestBuilder(uri, requestId).GET().build()
        val resp = send(req)
        if (resp.statusCode() !in 200..299) {
            throw httpError(uri, resp.statusCode(), resp.body(), requestId)
        }
        return resp.body()
    }

    private fun getBytes(endpoint: String, vararg params: Pair<String, String>): ByteArray {
        val uri = queryUri(endpoint, *params)
        val requestId = newRequestId()
        val req = requestBuilder(uri, requestId).GET().build()
        val resp = try {
            client.send(req, HttpResponse.BodyHandlers.ofByteArray())
        } catch (e: IOException) {
            throw VfsBackendException("request to $uri failed: ${e.message}", e)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
            throw VfsBackendException("request to $uri interrupted", e)
        }
        if (resp.statusCode() !in 200..299) {
            throw httpError(uri, resp.statusCode(), resp.body().decodeToString(), requestId)
        }
        return resp.body()
    }

    private fun post(endpoint: String, jsonBody: String): String {
        val uri = queryUri(endpoint)
        val requestId = newRequestId()
        val req = requestBuilder(uri, requestId)
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
            .build()
        val resp = send(req)
        if (resp.statusCode() !in 200..299) {
            throw httpError(uri, resp.statusCode(), resp.body(), requestId)
        }
        return resp.body()
    }

    private fun put(endpoint: String, jsonBody: String, vararg params: Pair<String, String>): String {
        val uri = queryUri(endpoint, *params)
        val requestId = newRequestId()
        val req = requestBuilder(uri, requestId)
            .header("Content-Type", "application/json")
            .PUT(HttpRequest.BodyPublishers.ofString(jsonBody))
            .build()
        val resp = send(req)
        if (resp.statusCode() !in 200..299) {
            throw httpError(uri, resp.statusCode(), resp.body(), requestId)
        }
        return resp.body()
    }

    private fun delete(endpoint: String, vararg params: Pair<String, String>) {
        val uri = queryUri(endpoint, *params)
        val requestId = newRequestId()
        val req = requestBuilder(uri, requestId).DELETE().build()
        val resp = send(req)
        if (resp.statusCode() !in 200..299) {
            throw httpError(uri, resp.statusCode(), resp.body(), requestId)
        }
    }

    /**
     * Builds the exception for a non-2xx response, pulling the sidecar's
     * defined error object ({"detail", "code", "request_id"} — see
     * src-py/wtbot/api/errors.py) out of the body when present so callers
     * and log lines get the server's one-line explanation rather than raw
     * JSON. Non-JSON bodies (a proxy's HTML error page, an empty body) fall
     * back to the raw text.
     */
    private fun httpError(uri: URI, status: Int, body: String, requestId: String): VfsBackendException {
        val detail = runCatching { JsonReader(body).stringOrNull("detail") }.getOrNull()
        val errorCode = runCatching { JsonReader(body).stringOrNull("code") }.getOrNull()
        return VfsBackendException(
            "HTTP $status from $uri: ${detail ?: body.ifBlank { "<empty body>" }}",
            statusCode = status,
            detail = detail,
            errorCode = errorCode,
            requestId = requestId,
        )
    }

    /**
     * Wraps [HttpClient.send] so a down/unreachable sidecar (the common case
     * right after IDE launch, before wtbot has started) surfaces as
     * [VfsBackendException] like every other failure mode here, instead of a
     * raw [IOException]/[InterruptedException] that callers up the VFS chain
     * (e.g. [WtVirtualFileSystem.findFileByPath] during editor-tab restore)
     * don't expect and can't catch.
     */
    private fun send(req: HttpRequest): HttpResponse<String> =
        try {
            client.send(req, HttpResponse.BodyHandlers.ofString())
        } catch (e: IOException) {
            throw VfsBackendException("request to ${req.uri()} failed: ${e.message}", e)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
            throw VfsBackendException("request to ${req.uri()} interrupted", e)
        }

    /** Minimal JSON object writer — pairs of String key to String/Long/Boolean/null. */
    private fun buildJsonObject(vararg fields: Pair<String, Any?>): String =
        fields.joinToString(",", prefix = "{", postfix = "}") { (k, v) ->
            "\"${escapeJson(k)}\":${jsonValue(v)}"
        }

    private fun jsonValue(v: Any?): String = when (v) {
        null -> "null"
        is String -> "\"${escapeJson(v)}\""
        is Boolean, is Long, is Int, is Double -> v.toString()
        else -> "\"${escapeJson(v.toString())}\""
    }

    private fun escapeJson(s: String): String {
        val sb = StringBuilder(s.length)
        for (c in s) {
            when (c) {
                '"' -> sb.append("\\\"")
                '\\' -> sb.append("\\\\")
                '\n' -> sb.append("\\n")
                '\r' -> sb.append("\\r")
                '\t' -> sb.append("\\t")
                else -> if (c.code < 0x20) sb.append("\\u%04x".format(c.code)) else sb.append(c)
            }
        }
        return sb.toString()
    }
}

/**
 * Extends [IOException], not [RuntimeException]: [WtVirtualFile]'s
 * `contentsToByteArray()`/`getInputStream()` overrides implement a Java
 * `VirtualFile` contract that declares `throws IOException`, and IntelliJ
 * platform code around VFS content reads generally catches that — so a
 * down/unreachable sidecar degrades the same way there as everywhere else
 * that already explicitly catches [VfsBackendException].
 */
class VfsBackendException(
    message: String,
    cause: Throwable? = null,
    /** HTTP status when the failure was an HTTP error response; null for transport failures. */
    val statusCode: Int? = null,
    /** The sidecar error object's human-readable "detail", when the body carried one. */
    val detail: String? = null,
    /** The sidecar error object's stable "code" (e.g. "scan-image-fetch-failed"). */
    val errorCode: String? = null,
    /** The X-Request-Id this client sent — the sidecar logs and echoes it. */
    val requestId: String? = null,
) : IOException(message, cause)
