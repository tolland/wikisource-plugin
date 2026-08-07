package org.limepepper.lang.wikitext.vfs.settings

import com.intellij.openapi.application.ApplicationManager
import com.intellij.testFramework.fixtures.BasePlatformTestCase
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference

class WtbotAppSettingsTest : BasePlatformTestCase() {

    private lateinit var settings: WtbotAppSettings

    override fun setUp() {
        super.setUp()
        settings = WtbotAppSettings.getInstance()
        val original = settings.getState()
        // The settings service is application-scoped and outlives the test, so
        // put it back the way it was found.
        com.intellij.openapi.util.Disposer.register(testRootDisposable) {
            settings.update(original.baseUrl, original.timeoutSeconds)
        }
    }

    fun testUpdateNotifiesListenerOnceWithBothValues() {
        val received = AtomicReference<Pair<WtbotAppSettings.State, WtbotAppSettings.State>?>(null)
        val calls = AtomicInteger()
        ApplicationManager.getApplication().messageBus.connect(testRootDisposable)
            .subscribe(WtbotAppSettings.TOPIC, WtbotSettingsListener { previous, current ->
                calls.incrementAndGet()
                received.set(previous to current)
            })

        settings.update("http://example.org:9001", 42)

        assertEquals(1, calls.get())
        assertEquals("http://example.org:9001", received.get()?.second?.baseUrl)
        assertEquals(42, received.get()?.second?.timeoutSeconds)
        assertEquals("http://example.org:9001", settings.baseUrl)
        assertEquals(42, settings.timeoutSeconds)
    }

    fun testNoEventWhenNothingChanged() {
        settings.update("http://example.org:9001", 42)

        val calls = AtomicInteger()
        ApplicationManager.getApplication().messageBus.connect(testRootDisposable)
            .subscribe(WtbotAppSettings.TOPIC, WtbotSettingsListener { _, _ -> calls.incrementAndGet() })

        settings.update("http://example.org:9001", 42)

        assertEquals(0, calls.get())
    }

    /** A timeout-only change must be distinguishable, so it can skip invalidation. */
    fun testTimeoutOnlyChangeCarriesUnchangedBaseUrl() {
        settings.update("http://example.org:9001", 42)
        val received = AtomicReference<Pair<WtbotAppSettings.State, WtbotAppSettings.State>?>(null)
        ApplicationManager.getApplication().messageBus.connect(testRootDisposable)
            .subscribe(WtbotAppSettings.TOPIC, WtbotSettingsListener { previous, current ->
                received.set(previous to current)
            })

        settings.update("http://example.org:9001", 7)

        val (previous, current) = received.get()!!
        assertEquals(previous.baseUrl, current.baseUrl)
        assertEquals(7, current.timeoutSeconds)
    }

    fun testBaseUrlNormalization() {
        assertEquals("http://127.0.0.1:18574", WtbotAppSettings.normalizeBaseUrl("http://127.0.0.1:18574/"))
        assertEquals("http://127.0.0.1:18574", WtbotAppSettings.normalizeBaseUrl("  http://127.0.0.1:18574  "))
        assertEquals("https://wtbot.lan", WtbotAppSettings.normalizeBaseUrl("https://wtbot.lan"))
        // A path prefix is legitimate — the sidecar can sit behind a reverse proxy.
        assertEquals("http://host:80/wtbot", WtbotAppSettings.normalizeBaseUrl("http://host:80/wtbot/"))
    }

    fun testBaseUrlRejectsUnusableValues() {
        assertNull(WtbotAppSettings.normalizeBaseUrl(null))
        assertNull(WtbotAppSettings.normalizeBaseUrl(""))
        assertNull(WtbotAppSettings.normalizeBaseUrl("   "))
        assertNull(WtbotAppSettings.normalizeBaseUrl("127.0.0.1:18574"))
        assertNull(WtbotAppSettings.normalizeBaseUrl("ftp://127.0.0.1:18574"))
        assertNull(WtbotAppSettings.normalizeBaseUrl("http://"))
        assertNull(WtbotAppSettings.normalizeBaseUrl("http://host?x=1"))
    }

    fun testUpdateRejectsUnusableBaseUrl() {
        assertThrows(IllegalArgumentException::class.java) {
            settings.update("not a url", 10)
        }
    }

    /** Hand-edited or stale config must not leave the backend unbuildable. */
    fun testLoadStateSanitisesGarbage() {
        val fresh = WtbotAppSettings()
        fresh.loadState(WtbotAppSettings.State(baseUrl = "nonsense", timeoutSeconds = -5))
        assertEquals(WtbotAppSettings.DEFAULT_BASE_URL, fresh.baseUrl)
        assertEquals(WtbotAppSettings.DEFAULT_TIMEOUT_SECONDS, fresh.timeoutSeconds)
    }

    fun testStartupPropertyOverridesPersistedValue() {
        val previous = System.getProperty(WtbotAppSettings.BASE_URL_PROPERTY)
        System.setProperty(WtbotAppSettings.BASE_URL_PROPERTY, "http://127.0.0.1:18584")
        try {
            val fresh = WtbotAppSettings()
            fresh.loadState(WtbotAppSettings.State(baseUrl = "http://persisted.example:1234", timeoutSeconds = 11))
            assertEquals("http://127.0.0.1:18584", fresh.baseUrl)
            // Only the overridden field is replaced.
            assertEquals(11, fresh.timeoutSeconds)
        } finally {
            if (previous == null) {
                System.clearProperty(WtbotAppSettings.BASE_URL_PROPERTY)
            } else {
                System.setProperty(WtbotAppSettings.BASE_URL_PROPERTY, previous)
            }
        }
    }

    fun testUnusableStartupPropertyIsIgnored() {
        val previous = System.getProperty(WtbotAppSettings.BASE_URL_PROPERTY)
        System.setProperty(WtbotAppSettings.BASE_URL_PROPERTY, "gopher://nope")
        try {
            val fresh = WtbotAppSettings()
            fresh.loadState(WtbotAppSettings.State(baseUrl = "http://persisted.example:1234", timeoutSeconds = 11))
            assertEquals("http://persisted.example:1234", fresh.baseUrl)
        } finally {
            if (previous == null) {
                System.clearProperty(WtbotAppSettings.BASE_URL_PROPERTY)
            } else {
                System.setProperty(WtbotAppSettings.BASE_URL_PROPERTY, previous)
            }
        }
    }
}
