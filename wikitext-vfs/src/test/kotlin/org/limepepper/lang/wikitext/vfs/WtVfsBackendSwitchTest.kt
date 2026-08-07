package org.limepepper.lang.wikitext.vfs

import com.intellij.testFramework.fixtures.BasePlatformTestCase
import org.limepepper.lang.wikitext.vfs.backend.FakeVfsBackend
import org.limepepper.lang.wikitext.vfs.backend.HttpVfsBackend
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import org.limepepper.lang.wikitext.vfs.settings.WtbotAppSettings

/**
 * The behaviour the settings page exists for: changing the sidecar URL moves
 * the live VFS onto it, and the files cached from the old one are rebuilt
 * rather than left showing its content.
 */
class WtVfsBackendSwitchTest : BasePlatformTestCase() {

    private lateinit var originalSettings: WtbotAppSettings.State
    private lateinit var originalBackend: VfsBackend

    override fun setUp() {
        super.setUp()
        originalSettings = WtbotAppSettings.getInstance().getState()
        originalBackend = WtVfsService.instance.backend
    }

    override fun tearDown() {
        try {
            WtbotAppSettings.getInstance().update(originalSettings.baseUrl, originalSettings.timeoutSeconds)
            WtVfsService.instance.setBackendForTesting(originalBackend)
        } finally {
            super.tearDown()
        }
    }

    fun testSettingsChangeReplacesLiveBackend() {
        WtbotAppSettings.getInstance().update("http://127.0.0.1:18599", 5)

        val backend = WtVfsService.instance.backend
        assertInstanceOf(backend, HttpVfsBackend::class.java)
        assertEquals("http://127.0.0.1:18599", (backend as HttpVfsBackend).getBaseUrlForTesting())
    }

    fun testTimeoutOnlyChangeStillReplacesBackendAtSameUrl() {
        WtbotAppSettings.getInstance().update("http://127.0.0.1:18599", 5)
        WtbotAppSettings.getInstance().update("http://127.0.0.1:18599", 25)

        val backend = WtVfsService.instance.backend as HttpVfsBackend
        assertEquals("http://127.0.0.1:18599", backend.getBaseUrlForTesting())
    }

    fun testRebindKeepsIdentityRefetchesContentAndDropsMissingPaths() {
        val fileSystem = WtVirtualFileSystem()
        val before = FakeVfsBackend()
            .addDirectory("/mywikisource/en")
            .addFile("/mywikisource/en/Alpha", "old alpha")
            .addFile("/mywikisource/en/Beta", "old beta")
        WtVfsService.instance.setBackendForTesting(before)

        val alpha = fileSystem.getOrCreate("/mywikisource/en/Alpha", "Alpha", isDir = false)
        val beta = fileSystem.getOrCreate("/mywikisource/en/Beta", "Beta", isDir = false)
        assertEquals("old alpha", String(alpha.contentsToByteArray()))
        assertEquals("old beta", String(beta.contentsToByteArray()))

        // The new sidecar has Alpha with different content and no Beta at all.
        val after = FakeVfsBackend()
            .addDirectory("/mywikisource/en")
            .addFile("/mywikisource/en/Alpha", "new alpha")
        WtVfsService.instance.setBackendForTesting(after)

        val outcome = fileSystem.rebindToCurrentBackend()

        assertEquals(listOf(alpha), outcome.surviving)
        assertEquals(listOf(beta), outcome.missing)

        // Same instance for the same path — open editors and tree nodes hold it.
        assertSame(alpha, fileSystem.findFileByPath("/mywikisource/en/Alpha"))
        assertEquals("new alpha", String(alpha.contentsToByteArray()))

        // The vanished path is evicted, so nothing hands out the dead instance.
        assertNull(fileSystem.findFileByPath("/mywikisource/en/Beta"))
        assertTrue(beta.isValid)
        beta.markInvalid() // what WtBackendSwitcher does once editors are closed
        assertFalse(beta.isValid)
    }

    fun testRebindKeepsFilesWhenNewBackendIsUnreachable() {
        val fileSystem = WtVirtualFileSystem()
        val before = FakeVfsBackend().addFile("/mywikisource/en/Alpha", "old alpha")
        WtVfsService.instance.setBackendForTesting(before)
        val alpha = fileSystem.getOrCreate("/mywikisource/en/Alpha", "Alpha", isDir = false)
        assertEquals("old alpha", String(alpha.contentsToByteArray()))

        // Port 1 refuses connections; a down sidecar must not invalidate files.
        WtVfsService.instance.setBackendForTesting(HttpVfsBackend("http://127.0.0.1:1"))
        val outcome = fileSystem.rebindToCurrentBackend()

        assertEquals(listOf(alpha), outcome.surviving)
        assertTrue(outcome.missing.isEmpty())
        assertTrue(alpha.isValid)
        // Content was dropped even so — nothing from the old sidecar survives.
        assertNull(alpha.cachedContent)
    }
}
