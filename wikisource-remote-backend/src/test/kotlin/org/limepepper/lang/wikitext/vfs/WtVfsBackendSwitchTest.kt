package org.limepepper.lang.wikitext.vfs

import com.intellij.testFramework.fixtures.BasePlatformTestCase
import org.limepepper.lang.wikitext.vfs.backend.HttpVfsBackend
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import org.limepepper.lang.wikitext.vfs.settings.WtbotAppSettings

/** Settings replace the live client; managed file rebinding is covered by WtManagedBackendFileSystemTest. */
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

}
