package org.limepepper.lang.wikitext

import org.junit.jupiter.api.extension.AfterEachCallback
import org.junit.jupiter.api.extension.BeforeEachCallback
import org.junit.jupiter.api.extension.ExtensionContext
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.file.Path
import java.time.Duration
import java.util.concurrent.TimeUnit
import kotlin.io.path.createDirectories
import kotlin.io.path.exists

@Target(AnnotationTarget.FUNCTION)
@Retention(AnnotationRetention.RUNTIME)
annotation class WithWtbot

/** Starts a real local API only for tests annotated with [WithWtbot]. */
class WtbotServerExtension : BeforeEachCallback, AfterEachCallback {
    private var process: Process? = null
    private var launchBuilder: ProcessBuilder? = null
    var baseUrl: String? = null
        private set

    override fun beforeEach(context: ExtensionContext) {
        if (!context.requiredTestMethod.isAnnotationPresent(WithWtbot::class.java)) return
        val root = generateSequence(Path.of("").toAbsolutePath()) { it.parent }
            .firstOrNull { it.resolve("src-py/wtbot/main.py").exists() }
            ?: error("Run IDE tests with a working directory inside the repository")
        val directory = java.nio.file.Files.createTempDirectory(
            root.resolve("build/ide-backends").createDirectories(), "${context.requiredTestMethod.name}-",
        )
        val log = directory.resolve("wtbot.log")
        // Fail instead of accidentally attaching to an existing developer/pytest API.
        ServerSocket().use { socket ->
            // Match Uvicorn's reuse behavior so a previous run's TIME_WAIT
            // connections do not prevent immediately rerunning the test.
            socket.reuseAddress = true
            socket.bind(InetSocketAddress("127.0.0.1", 18594))
        }
        val builder = ProcessBuilder(
            "uv", "run", "--no-sync", "python", "-m", "ide_test_support",
            "--data-dir", directory.toString(), "--port", "18594", "--scenario", "browser",
        ).directory(root.toFile()).redirectErrorStream(true).redirectOutput(ProcessBuilder.Redirect.appendTo(log.toFile()))
        builder.environment().apply {
            put("PYTHONPATH", root.resolve("src-py").toString())
            put("WTBOT_DATABASE_URL", "sqlite:///${directory.resolve("wtbot.db")}")
            put("WTBOT_BLOB_ROOT", directory.resolve("blobs").toString())
            put("WTBOT_PORT", "18594")
            put("WTBOT_FAILURE_LOG", directory.resolve("failure.log").toString())
        }
        println("Managed wtbot artifacts: $directory")
        launchBuilder = builder
        startServer()
    }

    private fun startServer() {
        val builder = requireNotNull(launchBuilder)
        val log = builder.redirectOutput().file()
        try {
            val child = builder.start()
            process = child
            val url = "http://127.0.0.1:18594"
            val client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build()
            val request = HttpRequest.newBuilder(URI.create("$url/health"))
                .timeout(Duration.ofSeconds(2)).GET().build()
            val deadline = System.nanoTime() + TimeUnit.SECONDS.toNanos(60)
            while (System.nanoTime() < deadline) {
                check(child.isAlive) { "wtbot exited (${child.exitValue()}); see $log" }
                val ready = runCatching {
                    client.send(request, HttpResponse.BodyHandlers.ofString()).statusCode() == 200
                }.getOrDefault(false)
                if (ready) {
                    baseUrl = url
                    return
                }
                Thread.sleep(200)
            }
            error("wtbot did not become ready within 60 seconds; see $log")
        } catch (failure: Throwable) {
            stop()
            throw failure
        }
    }

    override fun afterEach(context: ExtensionContext) = stop()

    fun restartServer() {
        check(process == null) { "Stop the owned backend before restarting it" }
        val builder = requireNotNull(launchBuilder)
        if ("--resume" !in builder.command()) builder.command(builder.command() + "--resume")
        startServer()
    }

    fun replaceDatabase(lastPage: Int) {
        stopServer()
        val builder = requireNotNull(launchBuilder)
        val directory = java.nio.file.Files.createTempDirectory(builder.directory().toPath().resolve("build/ide-backends"), "replacement-")
        val args = builder.command().toMutableList()
        args.remove("--resume")
        args[args.indexOf("--data-dir") + 1] = directory.toString()
        val indexArg = args.indexOf("--index-last-page")
        if (indexArg >= 0) args[indexArg + 1] = lastPage.toString()
        else args.addAll(listOf("--index-last-page", lastPage.toString()))
        builder.command(args)
        builder.environment()["WTBOT_DATABASE_URL"] = "sqlite:///${directory.resolve("wtbot.db")}"
        builder.environment()["WTBOT_BLOB_ROOT"] = directory.resolve("blobs").toString()
        builder.environment()["WTBOT_FAILURE_LOG"] = directory.resolve("failure.log").toString()
        // Keep the scenario log together across owned replacement processes.
        startServer()
    }

    fun stall(method: String = "", path: String = "", seconds: Int = 0) {
        val encoded = URLEncoder.encode(path, Charsets.UTF_8)
        val request = HttpRequest.newBuilder(URI.create("${requireNotNull(baseUrl)}/__ide_test/stall?method=$method&path=$encoded&seconds=$seconds"))
            .version(HttpClient.Version.HTTP_1_1).timeout(Duration.ofSeconds(10))
            .POST(HttpRequest.BodyPublishers.noBody()).build()
        check(HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString()).statusCode() == 204)
    }

    fun revise(path: String, text: String, revid: Long) {
        val encoded = URLEncoder.encode(path, Charsets.UTF_8)
        val request = HttpRequest.newBuilder(URI.create("${requireNotNull(baseUrl)}/__ide_test/revise?path=$encoded&revid=$revid"))
            .version(HttpClient.Version.HTTP_1_1)
            .timeout(Duration.ofSeconds(10))
            .header("Content-Type", "text/plain; charset=utf-8")
            .POST(HttpRequest.BodyPublishers.ofString(text)).build()
        val response = HttpClient.newHttpClient().send(request, HttpResponse.BodyHandlers.ofString())
        check(response.statusCode() == 204) { "Revision injection failed: ${response.statusCode()}: ${response.body()}" }
    }

    fun stopServer() {
        process?.let { child ->
            // uv can retain a child Python process; terminate the whole owned tree.
            val descendants = child.descendants().toList()
            descendants.forEach { it.destroy() }
            child.destroy()
            if (!child.waitFor(15, TimeUnit.SECONDS)) child.destroyForcibly()
            descendants.filter { it.isAlive }.forEach { it.destroyForcibly() }
        }
        process = null
    }

    private fun stop() {
        stopServer()
        launchBuilder = null
        baseUrl = null
    }
}
