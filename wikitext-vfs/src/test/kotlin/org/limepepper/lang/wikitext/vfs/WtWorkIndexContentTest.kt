package org.limepepper.lang.wikitext.vfs

import org.junit.Assert.*
import org.junit.Test
import org.limepepper.lang.wikitext.vfs.backend.*
import java.io.IOException

class WtWorkIndexContentTest {
    private val index = "/ide/en/Index/Partial.djvu"
    private val page = "/ide/en/Page/Partial.djvu"
    private val paths = listOf("$index/@wikitext") + (1..4).map { "$page/$it/@wikitext" }
    private val work = WtAttachedWork("work", "test-backend", "database", WtManagedAddress.fromPath(index),
        paths.map(WtManagedAddress::fromPath))

    private fun stats() = paths.mapIndexed { number, path ->
        StatResult(path, true, kind = NodeKind.file, contentModel = if (number == 0) "proofread-index" else "proofread-page",
            revid = if (number <= 1) 10L else null, placeholder = number >= 2, dirty = number == 4,
            length = 1000, databaseId = "database")
    }

    private fun backend(rows: List<StatResult> = stats()): VfsBackend = object : VfsBackend by FakeVfsBackend() {
        override val cacheIdentity = "test-backend"
        override val requiresDatabaseIdentity = true
        override fun statBulk(paths: List<String>): List<StatResult> {
            assertEquals(this@WtWorkIndexContentTest.paths, paths)
            return rows
        }
        override fun readContent(path: String): ContentResult = error("Selection read content: $path")
        override fun listChildren(path: String): ListChildrenResult = error("Selection traversed a directory: $path")
    }

    @Test fun `metadata includes remote content and local edits but excludes both kinds of untouched default`() {
        // Pages 2 and 3 can have scaffold or OCR defaults of any length. Page 4
        // is a locally saved transcription with no remote revision yet.
        assertEquals(listOf(paths[0], paths[1], paths[4]),
            indexableWorkContent(backend(), work).map { it.backendPath })
    }

    @Test fun `explicitly saving the proposed body makes it eligible without a text comparison`() {
        val rows = stats().map { if (it.path == paths[2]) it.copy(dirty = true) else it }
        assertTrue(indexableWorkContent(backend(rows), work).any { it.backendPath == paths[2] })
    }

    @Test fun `unknown models properties and confirmed missing files do not enter the set`() {
        val rows = stats().map {
            when (it.path) {
                paths[1] -> it.copy(contentModel = "json")
                paths[4] -> it.copy(exists = false)
                else -> it
            }
        }
        assertEquals(listOf(work.content.first()), indexableWorkContent(backend(rows), work))
    }

    @Test fun `stale backend database missing Index and incomplete bulk responses fail closed`() {
        assertThrows(IOException::class.java) { indexableWorkContent(backend(), work.copy(connection = "other")) }
        assertThrows(IOException::class.java) { indexableWorkContent(backend(), work.copy(databaseId = "other")) }
        assertThrows(IOException::class.java) { indexableWorkContent(backend(stats().dropLast(1)), work) }
        assertThrows(IOException::class.java) { indexableWorkContent(backend(stats().map { it.copy(databaseId = null) }), work) }
        assertThrows(IOException::class.java) {
            indexableWorkContent(backend(stats().map { if (it.path == paths[0]) it.copy(exists = false) else it }), work)
        }
    }
}
