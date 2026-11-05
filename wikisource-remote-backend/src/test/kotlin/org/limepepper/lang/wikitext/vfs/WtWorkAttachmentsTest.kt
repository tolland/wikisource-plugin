package org.limepepper.lang.wikitext.vfs

import org.junit.Assert.*
import org.junit.Test
import org.limepepper.lang.wikitext.vfs.backend.*
import java.io.IOException

class WtWorkAttachmentsTest {
    private val index = "/ide/en/Index/Book.djvu"
    private val page = "/ide/en/Page/Book.djvu"

    private inner class Backend : VfsBackend by FakeVfsBackend() {
        val fake = FakeVfsBackend()
            .addDirectory(index)
            .addFile("$index/@wikitext", "Index", contentModel = "proofread-index")
            .addDirectory("$index/@pages")
            .addDirectory("$page/1", parent = "$index/@pages")
            .addDirectory("$page/2", parent = "$index/@pages")
            .addFile("$page/1/@wikitext", "One", contentModel = "proofread-page")
            .addFile("$page/2/@wikitext", "Two", contentModel = "proofread-page")
            .addFile("$page/1/@props", "{}", contentModel = "json")
        var database = "database-A"
        var unavailable = false
        var lastPage = 2
        var duringBulk: () -> Unit = {}
        var duringList: () -> Unit = {}
        val listings = mutableListOf<String>()
        override val cacheIdentity = "http://test-wtbot"
        override val requiresDatabaseIdentity = true
        override fun stat(path: String): StatResult {
            if (unavailable) throw IOException("Offline")
            return fake.stat(path).copy(databaseId = database)
        }
        override fun statBulk(paths: List<String>): List<StatResult> {
            duringBulk()
            return paths.map(::stat)
        }
        override fun listChildren(path: String): ListChildrenResult {
            listings += path
            duringList()
            return fake.listChildren(path).copy(databaseId = database,
                children = fake.listChildren(path).children.take(lastPage))
        }
        override fun pageNav(path: String) = PageNavResult(
            PageNavEntry(path, "Book.djvu/1"), index, "Index:Book.djvu", position = 1, total = 2)
    }

    @Test fun `attachment is bounded canonical and idempotent from either seed`() {
        val backend = Backend()
        val service = WtWorkAttachments()
        val first = service.attach(WtManagedAddress.fromPath(index), backend)
        val second = service.attach(WtManagedAddress.fromPath("$page/1/@wikitext"), backend)
        assertEquals(first.id, second.id)
        assertEquals(listOf(second), service.attachments())
        assertEquals(listOf("$index/@wikitext", "$page/1/@wikitext", "$page/2/@wikitext"),
            second.content.map { it.backendPath })
        assertTrue(backend.listings.all { it == "$index/@pages" })
    }

    @Test fun `membership snapshot survives state restore and updates only on refresh`() {
        val backend = Backend()
        val original = WtWorkAttachments()
        val work = original.attach(WtManagedAddress.fromPath(index), backend)
        val restored = WtWorkAttachments().also { it.loadState(original.getState()) }
        assertEquals(listOf(work), restored.attachments())
        backend.lastPage = 1
        assertEquals(3, restored.attachments().single().content.size)
        val updated = restored.refresh(work.id, backend)
        assertEquals(work.id, updated.id)
        assertEquals(listOf("$index/@wikitext", "$page/1/@wikitext"), updated.content.map { it.backendPath })
        // Returned serialization state is a copy, not an editable service backing list.
        restored.getState().works.clear()
        assertEquals(listOf(updated), restored.attachments())
    }

    @Test fun `outage missing Index and replacement database retain confirmed membership`() {
        val backend = Backend()
        val service = WtWorkAttachments()
        val work = service.attach(WtManagedAddress.fromPath(index), backend)
        backend.unavailable = true
        assertThrows(IOException::class.java) { service.refresh(work.id, backend) }
        backend.unavailable = false
        backend.database = "database-B"
        assertThrows(IOException::class.java) { service.refresh(work.id, backend) }
        assertThrows(IOException::class.java) { service.attach(WtManagedAddress.fromPath(index), backend) }
        assertThrows(IOException::class.java) { service.checkAvailable(work, backend) }
        val missing = object : VfsBackend by backend {
            override fun stat(path: String) = backend.stat(path).copy(exists = false)
        }
        assertThrows(IOException::class.java) { service.refresh(work.id, missing) }
        assertEquals(listOf(work), service.attachments())
        backend.database = "database-A"
        service.checkAvailable(work, backend)
        assertEquals(work, service.refresh(work.id, backend))
    }

    @Test fun `database change midway through discovery cannot attach mixed membership`() {
        val backend = Backend().apply { duringList = { database = "database-B" } }
        val service = WtWorkAttachments()
        assertThrows(IOException::class.java) { service.attach(WtManagedAddress.fromPath(index), backend) }
        assertTrue(service.attachments().isEmpty())
    }

    @Test fun `detach during a refresh request cannot resurrect association or mutate content`() {
        val backend = Backend()
        val service = WtWorkAttachments()
        val work = service.attach(WtManagedAddress.fromPath(index), backend)
        backend.duringBulk = { service.detach(work.id) }
        assertThrows(IOException::class.java) { service.refresh(work.id, backend) }
        assertTrue(service.attachments().isEmpty())
        assertEquals("One", backend.fake.readContent("$page/1/@wikitext").decodeText())
    }
}
