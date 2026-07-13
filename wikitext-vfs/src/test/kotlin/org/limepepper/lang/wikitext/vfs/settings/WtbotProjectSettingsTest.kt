package org.limepepper.lang.wikitext.vfs.settings

import com.intellij.testFramework.fixtures.BasePlatformTestCase
import org.junit.Assert.assertEquals
import java.util.concurrent.atomic.AtomicReference

class WtbotProjectSettingsTest : BasePlatformTestCase() {

    fun testSettingsAndListenerNotified() {
        val proj = project
        val settings = WtbotProjectSettings.getInstance(proj)
        val received = AtomicReference<WtbotProjectSettings.State?>(null)
        val connection = proj.messageBus.connect(testRootDisposable)
        connection.subscribe(WtbotProjectSettings.TOPIC, WtbotSettingsListener { state ->
            received.set(state)
        })

        settings.host = "example.org"
        settings.port = 9001
        settings.timeoutSeconds = 42

        // Listener should receive the last state
        val state = received.get()
        assertEquals("example.org", state?.host)
        assertEquals(9001, state?.port)
        assertEquals(42, state?.timeoutSeconds)
        assertEquals("http://example.org:9001", settings.baseUrl)
    }

    fun testHttpVfsBackendUsesProjectSettings() {
        val proj = project
        val settings = WtbotProjectSettings.getInstance(proj)
        settings.host = "127.0.0.2"
        settings.port = 12345
        settings.timeoutSeconds = 7

        val backend = org.limepepper.lang.wikitext.vfs.backend.HttpVfsBackend(proj)
        assertEquals("http://127.0.0.2:12345", backend.getBaseUrlForTesting())
    }
}
