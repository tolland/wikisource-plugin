package org.limepepper.lang.wikitext.vfs.backend

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.Service
import com.intellij.openapi.diagnostic.Logger
import com.intellij.util.messages.Topic
import org.jetbrains.annotations.TestOnly
import org.limepepper.lang.wikitext.vfs.settings.WtbotAppSettings
import org.limepepper.lang.wikitext.vfs.settings.WtbotSettingsListener
import java.time.Duration

/**
 * Application-level service that owns the live [VfsBackend].
 *
 * Registered in wikisource.wikitext-vfs.xml as an applicationService.
 * Retrieve via [WtVfsService.instance].
 *
 * The backend is built from [WtbotAppSettings] and *replaced* — never mutated
 * in place — when those settings change, so a switch is a single volatile
 * write that every caller picks up on its next `instance.backend` read. Callers
 * must therefore not hold a [VfsBackend] reference across operations; they all
 * re-read it per call today, which is what makes switching sidecars at runtime
 * work without restarting the IDE.
 *
 * A base-URL change also invalidates the plugin-side caches built from the old
 * sidecar (see [WtBackendSwitcher]); a timeout-only change just swaps the
 * client.
 */
@Service(Service.Level.APP)
class WtVfsService : Disposable {

    @Volatile
    private var currentBackend: VfsBackend = buildBackend()

    /** The backend in force right now. Re-read this per operation. */
    val backend: VfsBackend get() = currentBackend

    init {
        ApplicationManager.getApplication().messageBus.connect(this).subscribe(
            WtbotAppSettings.TOPIC,
            WtbotSettingsListener { previous, current ->
                currentBackend = buildBackend()
                LOG.info("wtbot backend now ${current.baseUrl} (timeout ${current.timeoutSeconds}s)")
                if (previous.baseUrl != current.baseUrl) {
                    // Everything cached on the plugin side describes the old
                    // sidecar's SQLite state and has to be rebuilt.
                    WtBackendSwitcher.rebuildAfterSwitch(current.baseUrl)
                }
            },
        )
    }

    override fun dispose() {}

    /**
     * Replaces the live backend without going through settings. Tests only —
     * production switching happens via [WtbotAppSettings.update] so that the
     * cache invalidation in [WtBackendSwitcher] runs too.
     */
    @TestOnly
    fun setBackendForTesting(backend: VfsBackend) {
        currentBackend = backend
    }

    companion object {
        private val LOG = Logger.getInstance(WtVfsService::class.java)

        private fun buildBackend(): VfsBackend {
            val settings = WtbotAppSettings.getInstance()
            return HttpVfsBackend(
                baseUrl = settings.baseUrl,
                timeout = Duration.ofSeconds(settings.timeoutSeconds.toLong()),
            )
        }

        /**
         * Fired on the EDT once a base-URL switch has finished invalidating
         * the VFS caches — the cue for UI that renders backend state (the tool
         * window tree, preview panes) to reload.
         */
        val BACKEND_SWITCHED: Topic<WtBackendSwitchedListener> =
            Topic.create("WtVfsBackendSwitched", WtBackendSwitchedListener::class.java)

        @JvmStatic
        val instance: WtVfsService
            get() = ApplicationManager.getApplication().getService(WtVfsService::class.java)
    }
}

/** Notified after the VFS has been rebound to a different wtbot sidecar. */
fun interface WtBackendSwitchedListener {
    fun backendSwitched(baseUrl: String)
}
