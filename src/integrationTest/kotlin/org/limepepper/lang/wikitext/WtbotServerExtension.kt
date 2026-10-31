package org.limepepper.lang.wikitext

import org.junit.jupiter.api.extension.AfterEachCallback
import org.junit.jupiter.api.extension.BeforeEachCallback
import org.junit.jupiter.api.extension.ExtensionContext
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.URI
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
        ).directory(root.toFile()).redirectErrorStream(true).redirectOutput(log.toFile())
        builder.environment().apply {
            put("PYTHONPATH", root.resolve("src-py").toString())
            put("WTBOT_DATABASE_URL", "sqlite:///${directory.resolve("wtbot.db")}")
            put("WTBOT_BLOB_ROOT", directory.resolve("blobs").toString())
            put("WTBOT_PORT", "18594")
            put("WTBOT_FAILURE_LOG", directory.resolve("failure.log").toString())
        }
        println("Managed wtbot artifacts: $directory")
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

    private fun stop() {
        process?.let { child ->
            // uv can retain a child Python process; terminate the whole owned tree.
            val descendants = child.descendants().toList()
            descendants.forEach { it.destroy() }
            child.destroy()
            if (!child.waitFor(15, TimeUnit.SECONDS)) child.destroyForcibly()
            descendants.filter { it.isAlive }.forEach { it.destroyForcibly() }
        }
        process = null
        baseUrl = null
    }
}
