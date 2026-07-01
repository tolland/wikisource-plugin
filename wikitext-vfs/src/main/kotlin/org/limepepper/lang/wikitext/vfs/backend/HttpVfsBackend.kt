package org.limepepper.lang.wikitext.vfs.backend

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
        val resp = client.send(req, HttpResponse.BodyHandlers.ofString())
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
        val resp = client.send(req, HttpResponse.BodyHandlers.ofString())
        if (resp.statusCode() !in 200..299) {
            throw VfsBackendException("HTTP ${resp.statusCode()} from $uri: ${resp.body()}")
        }
        return resp.body()
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

class VfsBackendException(message: String, cause: Throwable? = null) :
    RuntimeException(message, cause)
