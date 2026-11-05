package org.limepepper.wikisource.remote.rpc

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.limepepper.lang.wikitext.vfs.backend.FakeVfsBackend
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService

class WtRemotePageRpcServiceImplTest {

    @Test
    fun testFetchAndSavePage() = runBlocking {
        val fakeBackend = FakeVfsBackend()
        fakeBackend.addFile("/en/Page:Test.djvu/1/@wikitext", "Sample content")
        WtVfsService.instance.setBackendForTesting(fakeBackend)

        val service = WtRemotePageRpcServiceImpl()
        val pageId = PageIdentifier("en", "Page:Test.djvu/1")

        val snapshot = service.fetchPage(pageId)
        assertEquals("Sample content", snapshot.content)

        val saved = service.savePage(pageId, "Updated content", "test edit")
        assertTrue(saved)

        val updatedSnapshot = service.fetchPage(pageId)
        assertEquals("Updated content", updatedSnapshot.content)
    }
}
