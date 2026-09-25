package org.limepepper.lang.wikitext.uitest

import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration

/**
 * The wtbot sidecar the IDE under test is pointed at.
 *
 * The docker backend (`uiTestBackendUp`) starts with an empty database, so
 * anything a test expects to see in the IDE is registered here first, over
 * the same HTTP contract the plugin and the `wtbot` CLI use.
 */
class WtbotTestBackend(val baseUrl: String) {
    private val http: HttpClient = HttpClient.newBuilder()
        // uvicorn answers the default h2c upgrade on a POST with 400.
        .version(HttpClient.Version.HTTP_1_1)
        .connectTimeout(Duration.ofSeconds(5))
        .build()

    fun isHealthy(): Boolean = runCatching { get("/health").statusCode() == 200 }.getOrDefault(false)

    /** Registers [site]; an existing registration under the same label is fine (409). */
    fun ensureSite(site: TestSite) {
        val body = """
            {"family": "${site.family}", "code": "${site.code}", "label": "${site.label}",
             "api_url": "${site.apiUrl}", "read_throttle": 0}
        """.trimIndent()
        val response = post("/sites/", body)
        check(response.statusCode() in setOf(201, 409)) {
            "registering ${site.label} failed: ${response.statusCode()} ${response.body()}"
        }
    }

    private fun get(path: String): HttpResponse<String> =
        http.send(request(path).GET().build(), HttpResponse.BodyHandlers.ofString())

    private fun post(path: String, json: String): HttpResponse<String> =
        http.send(
            request(path)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(json))
                .build(),
            HttpResponse.BodyHandlers.ofString(),
        )

    private fun request(path: String): HttpRequest.Builder =
        HttpRequest.newBuilder(URI.create(baseUrl.trimEnd('/') + path)).timeout(Duration.ofSeconds(30))

    companion object {
        fun fromSystemProperties(): WtbotTestBackend =
            WtbotTestBackend(requireNotNull(System.getProperty("wtbot.baseUrl")) { "wtbot.baseUrl not set" })
    }
}

/** A wiki registration; the VFS root lists it as `family/code`. */
data class TestSite(
    val family: String,
    val code: String,
    val label: String,
    val apiUrl: String,
) {
    val vfsName: String get() = "$family/$code"
}
