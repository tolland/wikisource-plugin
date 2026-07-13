package org.limepepper.lang.wikitext.vfs.settings

import com.intellij.testFramework.fixtures.BasePlatformTestCase
import org.junit.Assert.assertEquals
import java.util.concurrent.atomic.AtomicReference

class WtbotProjectSettingsTest : BasePlatformTestCase() {

    fun testSettingsAndListenerNotified() {
        val project = myProject
        val settings = WtbotProjectSettings.getInstance(project)
        val received = AtomicReference<WtbotProjectSettings.State?>(null)
        val connection = project.messageBus.connect(testRootDisposable)
        connection.subscribe(WtbotProjectSettings.TOPIC) { state ->
            received.set(state)
        }

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
        val project = myProject
        val settings = WtbotProjectSettings.getInstance(project)
        settings.host = "127.0.0.2"
        settings.port = 12345
        settings.timeoutSeconds = 7

        val backend = org.limepepper.lang.wikitext.vfs.backend.HttpVfsBackend(project)
        assertEquals("http://127.0.0.2:12345", backend.getBaseUrlForTesting())
    }
}
