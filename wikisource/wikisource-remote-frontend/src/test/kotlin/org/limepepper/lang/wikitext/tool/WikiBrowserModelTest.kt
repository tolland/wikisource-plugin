package org.limepepper.lang.wikitext.tool

import org.junit.Assert.*
import org.junit.Test
import org.limepepper.lang.wikitext.vfs.backend.FakeVfsBackend
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend

class WikiBrowserModelTest {
    @Test fun `graph occurrences keep their own parents and refresh metadata`() {
        val page = "/ide/en/Page/Book/1"
        val base = FakeVfsBackend().addDirectory("/")
            .addDirectory("/ide/en", parent = "/")
            .addDirectory("/ide/en/Index")
        for (book in listOf("First", "Second")) {
            val title = "/ide/en/Index/$book"
            base.addDirectory(title).addDirectory("$title/@pages")
                .addDirectory(page, parent = "$title/@pages")
        }
        var databaseId = "first-database"
        var quality = 1
        val backend = object : VfsBackend by base {
            override fun listChildren(path: String) = base.listChildren(path).let { result ->
                result.copy(databaseId = databaseId, children = result.children.map {
                    if (it.path == page) it.copy(qualityLevel = quality) else it
                })
            }
        }
        val model = WikiBrowserModel { backend }
        val site = model.roots().single()
        val index = model.children(site).single()
        val books = model.children(index)
        val firstPages = model.children(books[0]).single()
        val secondPages = model.children(books[1]).single()
        val firstPage = model.children(firstPages).single()
        val secondPage = model.children(secondPages).single()
        assertEquals(firstPage.path, secondPage.path)
        assertNotEquals(firstPage, secondPage)
        assertEquals(firstPages, firstPage.parent)
        assertEquals(secondPages, secondPage.parent)
        quality = 3
        model.invalidate()
        assertEquals(firstPage, model.children(firstPages).single())
        assertEquals(3, firstPage.qualityLevel)
        databaseId = "replacement-database"
        assertNotEquals(site, model.roots().single())
    }
}
