package org.limepepper.lang.wikitext.vfs.backend

import java.io.IOException
import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

/**
 * Calls the wtbot FastAPI VFS endpoints over HTTP.
 *
 * Uses only the JDK HTTP client — no extra runtime dependencies.
 * JSON is parsed with a minimal hand-rolled extractor ([JsonReader]) rather
 * than a full library so the wikitext-vfs module stays dep-light.
 *
 * @param baseUrl  e.g. "http://127.0.0.1:8000" — no trailing slash
 * @param timeout  per-request timeout
 */
class HttpVfsBackend(
    private val baseUrl: String = "http://127.0.0.1:8000",
    private val timeout: Duration = Duration.ofSeconds(10),
    private val client: HttpClient = HttpClient.newBuilder()
        .connectTimeout(timeout)
        .build(),
) : VfsBackend {

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
                hasPageImage = boolOrDefault("has_page_image", false),
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
                hasPageImage = r.boolOrDefault("has_page_image", false),
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
                        hasPageImage = child.boolOrDefault("has_page_image", false),
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

    override fun pageImageUrl(path: String?, title: String?): String {
        val query = listOfNotNull(
            path?.let { "path" to it },
            title?.let { "title" to it },
        ).joinToString("&") { (k, v) ->
            "${URLEncoder.encode(k, "UTF-8")}=${URLEncoder.encode(v, "UTF-8")}"
        }
        return "$baseUrl/preview/page-image?$query"
    }

    // -------------------------------------------------------------------------

    private fun get(endpoint: String, vararg params: Pair<String, String>): String {
        val query = params.joinToString("&") { (k, v) ->
            "${URLEncoder.encode(k, "UTF-8")}=${URLEncoder.encode(v, "UTF-8")}"
        }
        val uri = URI.create("$baseUrl$endpoint?$query")
        val req = HttpRequest.newBuilder(uri)
            .timeout(timeout)
            .version(HttpClient.Version.HTTP_1_1) // avoid upgrade requests
            .GET()
            .build()
        val resp = send(req)
        if (resp.statusCode() !in 200..299) {
            throw VfsBackendException("HTTP ${resp.statusCode()} from $uri: ${resp.body()}")
        }
        return resp.body()
    }

    private fun post(endpoint: String, jsonBody: String): String {
        val uri = URI.create("$baseUrl$endpoint")
        val req = HttpRequest.newBuilder(uri)
            .timeout(timeout)
            .version(HttpClient.Version.HTTP_1_1) // avoid upgrade requests
            .header("Content-Type", "application/json")
            .POST(HttpRequest.BodyPublishers.ofString(jsonBody))
            .build()
        val resp = send(req)
        if (resp.statusCode() !in 200..299) {
            throw VfsBackendException("HTTP ${resp.statusCode()} from $uri: ${resp.body()}")
        }
        return resp.body()
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
        is Boolean, is Long, is Int -> v.toString()
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
class VfsBackendException(message: String, cause: Throwable? = null) :
    IOException(message, cause)
