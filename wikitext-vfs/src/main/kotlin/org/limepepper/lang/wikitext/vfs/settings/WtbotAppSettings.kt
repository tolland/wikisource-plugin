package org.limepepper.lang.wikitext.vfs.settings

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.Service.Level
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.openapi.diagnostic.Logger
import com.intellij.util.messages.Topic
import java.net.URI

/**
 * Application-level settings for the wtbot sidecar the VFS talks to.
 *
 * Application- rather than project-scoped on purpose: wtbot itself mediates
 * between wikis, so one sidecar serves every project, and the things that
 * consume this — [org.limepepper.lang.wikitext.vfs.backend.WtVfsService] and
 * the `wikisource://` filesystem with its path→file cache — are application
 * singletons with no project to scope to.
 *
 * Changes are published on [TOPIC] as a (previous, current) pair so listeners
 * can tell a base-URL switch (which invalidates every cached file) from a
 * timeout tweak (which does not).
 */
@State(name = "WtbotSettings", storages = [Storage("wikitext-vfs.xml")])
@Service(Level.APP)
class WtbotAppSettings : PersistentStateComponent<WtbotAppSettings.State> {

    data class State(
        var baseUrl: String = DEFAULT_BASE_URL,
        var timeoutSeconds: Int = DEFAULT_TIMEOUT_SECONDS,
    )

    @Volatile
    private var state: State = applyStartupOverrides(State())

    override fun getState(): State = state.copy()

    override fun loadState(state: State) {
        // Persisted values are sanitised on the way in: a hand-edited or
        // stale config file must not leave the backend pointed at a URL the
        // HTTP client can't build a request from.
        val sane = State(
            baseUrl = normalizeBaseUrl(state.baseUrl) ?: DEFAULT_BASE_URL,
            timeoutSeconds = state.timeoutSeconds.takeIf { it in TIMEOUT_RANGE } ?: DEFAULT_TIMEOUT_SECONDS,
        )
        this.state = applyStartupOverrides(sane)
    }

    override fun noStateLoaded() {
        state = applyStartupOverrides(State())
    }

    /** Normalised sidecar root, no trailing slash — e.g. `http://127.0.0.1:18574`. */
    val baseUrl: String get() = state.baseUrl

    /** Per-request timeout in seconds. */
    val timeoutSeconds: Int get() = state.timeoutSeconds

    /**
     * Sets both fields at once and publishes at most one [TOPIC] event.
     *
     * Deliberately not two setters: a settings-page Apply that moved host,
     * port and timeout would otherwise fire three events and drive three
     * cache invalidations for what the user did as one edit.
     *
     * @throws IllegalArgumentException if [baseUrl] is not a usable http(s) URL.
     */
    fun update(baseUrl: String, timeoutSeconds: Int) {
        val next = State(
            baseUrl = normalizeBaseUrl(baseUrl)
                ?: throw IllegalArgumentException("not a usable wtbot base URL: '$baseUrl'"),
            timeoutSeconds = timeoutSeconds,
        )
        val previous = state
        if (previous == next) return
        state = next
        ApplicationManager.getApplication().messageBus
            .syncPublisher(TOPIC)
            .settingsChanged(previous, next)
    }

    /**
     * Startup overrides from `-Dwtbot.baseUrl=…` / `WTBOT_BASE_URL` (and the
     * timeout equivalents), applied over whatever was persisted.
     *
     * This is what makes `./gradlew runIde -PwtbotBaseUrl=…` land on the right
     * sidecar: the sandbox keeps its config between runs, so a property that
     * only supplied a first-run default would be ignored on every later launch.
     * The override is written into the live state rather than layered on top of
     * it, so the settings page shows the URL actually in use and can still be
     * pointed somewhere else without restarting.
     */
    private fun applyStartupOverrides(base: State): State {
        var result = base
        readOverride(BASE_URL_PROPERTY, BASE_URL_ENV)?.let { raw ->
            val normalized = normalizeBaseUrl(raw)
            if (normalized == null) {
                LOG.warn("ignoring wtbot base URL override '$raw': not a usable http(s) URL")
            } else {
                LOG.info("wtbot base URL overridden at startup: $normalized")
                result = result.copy(baseUrl = normalized)
            }
        }
        readOverride(TIMEOUT_PROPERTY, TIMEOUT_ENV)?.let { raw ->
            val seconds = raw.trim().toIntOrNull()
            if (seconds == null || seconds !in TIMEOUT_RANGE) {
                LOG.warn("ignoring wtbot timeout override '$raw': expected $TIMEOUT_RANGE seconds")
            } else {
                result = result.copy(timeoutSeconds = seconds)
            }
        }
        return result
    }

    companion object {
        private val LOG = Logger.getInstance(WtbotAppSettings::class.java)

        /** The docker-compose default port for the sidecar (see AGENTS.md). */
        // Dev-convention port for a workstation-launched sidecar (docs/logging.md
        // §0); point at the docker harness per-launch via -PwtbotBaseUrl instead.
        const val DEFAULT_BASE_URL: String = "http://127.0.0.1:18564"
        const val DEFAULT_TIMEOUT_SECONDS: Int = 10

        /** Set by `runIde -PwtbotBaseUrl=…`; also settable on any IDE's VM options. */
        const val BASE_URL_PROPERTY: String = "wtbot.baseUrl"
        const val BASE_URL_ENV: String = "WTBOT_BASE_URL"
        const val TIMEOUT_PROPERTY: String = "wtbot.timeoutSeconds"
        const val TIMEOUT_ENV: String = "WTBOT_TIMEOUT_SECONDS"

        val TIMEOUT_RANGE: IntRange = 1..600

        val TOPIC: Topic<WtbotSettingsListener> =
            Topic.create("WtbotSettings", WtbotSettingsListener::class.java)

        fun getInstance(): WtbotAppSettings =
            ApplicationManager.getApplication().getService(WtbotAppSettings::class.java)

        /**
         * Canonical form of a user-supplied base URL, or null when it is not
         * one: absolute, http or https, with a host, and no trailing slash
         * (every caller appends a rooted path like `/vfs/stat`).
         */
        fun normalizeBaseUrl(raw: String?): String? {
            val trimmed = raw?.trim()?.trimEnd('/') ?: return null
            if (trimmed.isEmpty()) return null
            val uri = try {
                URI(trimmed)
            } catch (_: Exception) {
                return null
            }
            if (uri.scheme?.lowercase() !in setOf("http", "https")) return null
            if (uri.host.isNullOrEmpty()) return null
            if (!uri.query.isNullOrEmpty() || !uri.fragment.isNullOrEmpty()) return null
            return trimmed
        }
    }
}

/** Notified when the wtbot backend settings change. */
fun interface WtbotSettingsListener {
    fun settingsChanged(previous: WtbotAppSettings.State, current: WtbotAppSettings.State)
}

private fun readOverride(property: String, env: String): String? =
    System.getProperty(property)?.takeIf { it.isNotBlank() }
        ?: System.getenv(env)?.takeIf { it.isNotBlank() }
