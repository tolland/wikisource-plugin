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

    // -------------------------------------------------------------------------

    private fun get(endpoint: String, vararg params: Pair<String, String>): String {
        val query = params.joinToString("&") { (k, v) ->
            "${URLEncoder.encode(k, "UTF-8")}=${URLEncoder.encode(v, "UTF-8")}"
        }
        val uri = URI.create("$baseUrl$endpoint?$query")
        val req = HttpRequest.newBuilder(uri)
            .timeout(timeout)
            .GET()
            .build()
        val resp = client.send(req, HttpResponse.BodyHandlers.ofString())
        if (resp.statusCode() !in 200..299) {
            throw VfsBackendException("HTTP ${resp.statusCode()} from $uri: ${resp.body()}")
        }
        return resp.body()
    }
}

class VfsBackendException(message: String, cause: Throwable? = null) :
    RuntimeException(message, cause)
