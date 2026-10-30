package org.limepepper.lang.wikitext.vfs

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test
import org.limepepper.lang.wikitext.vfs.backend.FakeVfsBackend
import org.limepepper.lang.wikitext.vfs.backend.PageNavEntry
import org.limepepper.lang.wikitext.vfs.backend.PageNavResult
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend

class WtManagedWorkTest {
    private val index = "/mywikisource/en/Index/Book.pdf"
    private val pageOne = "/mywikisource/en/Page/Book.pdf/1"
    private val pageTwo = "/mywikisource/en/Page/Book.pdf/2"

    private fun backend(): VfsBackend {
        val fake = FakeVfsBackend()
            .addDirectory(index)
            .addFile("$index/@wikitext", "Index", contentModel = "proofread-index")
            .addFile("$index/@props", "{}", contentModel = "json")
            .addDirectory("$index/@pages")
            .addDirectory(pageOne, parent = "$index/@pages")
            .addFile("$pageOne/@wikitext", "First", contentModel = "proofread-page")
            .addFile("$pageOne/@props", "{}", contentModel = "json")
            .addDirectory(pageTwo, parent = "$index/@pages")
            .addFile("$pageTwo/@wikitext", "Second", contentModel = "proofread-page")
            .addDirectory("/mywikisource/en/Page/Other.pdf/1")
            .addFile("/mywikisource/en/Page/Other.pdf/1/@wikitext", "Other", contentModel = "proofread-page")
        return object : VfsBackend by fake {
            override fun pageNav(path: String) = PageNavResult(
                PageNavEntry(path, "Book.pdf/1"), index, "Index:Book.pdf", position = 1, total = 2)
        }
    }

    @Test fun `index seed discovers only canonical text for that work`() {
        val work = discoverManagedWork(backend(), WtManagedAddress.fromPath(index))
        assertEquals(index, work.index.backendPath)
        assertEquals(listOf("$index/@wikitext", "$pageOne/@wikitext", "$pageTwo/@wikitext"),
            work.content.map { it.backendPath })
        assertFalse(work.content.any { "/@pages/" in it.backendPath || it.backendPath.endsWith("/@props") })
    }

    @Test fun `page seed resolves the same work via backend navigation`() {
        val backend = backend()
        assertEquals(discoverManagedWork(backend, WtManagedAddress.fromPath(index)),
            discoverManagedWork(backend, WtManagedAddress.fromPath("$pageOne/@wikitext")))
    }
}
