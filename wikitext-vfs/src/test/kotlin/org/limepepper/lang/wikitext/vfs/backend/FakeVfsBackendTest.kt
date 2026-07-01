package org.limepepper.lang.wikitext.vfs.backend

import org.junit.Assert.*
import org.junit.Test

class FakeVfsBackendTest {

    private val backend = FakeVfsBackend().apply {
        addDirectory("/wikisource/en")
        addDirectory("/wikisource/en/Index:Foo.djvu", stableId = 1001)
        addDirectory("/wikisource/en/Index:Foo.djvu/Pages")
        addFile(
            "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1",
            content = "{{recto}} Page one.",
            name = "Page:Foo.djvu/1",
            stableId = 1003,
            revid = 5003,
            contentModel = "proofread-page",
        )
        addFile(
            "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/2",
            content = "{{verso}} Page two.",
            name = "Page:Foo.djvu/2",
            stableId = 1004, revid = 5004,
            contentModel = "proofread-page",
        )
        addDirectory("/wikisource/en/Index:Foo.djvu/File:Foo.djvu")
        addFile("/wikisource/en/Index:Foo.djvu/File:Foo.djvu/wikitext", content = "== Description ==")
    }

    @Test
    fun `stat returns exists=true for known directory`() {
        val r = backend.stat("/wikisource/en/Index:Foo.djvu")
        assertTrue(r.exists)
        assertEquals(NodeKind.directory, r.kind)
        assertEquals(1001L, r.stableId)
    }

    @Test
    fun `stat returns exists=false for unknown path`() {
        val r = backend.stat("/wikisource/en/Index:NoSuch")
        assertFalse(r.exists)
        assertNull(r.kind)
    }

    @Test
    fun `stat file has correct length`() {
        val r = backend.stat("/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1")
        assertTrue(r.exists)
        assertEquals(NodeKind.file, r.kind)
        assertEquals("{{recto}} Page one.".toByteArray().size.toLong(), r.length)
    }

    @Test
    fun `listChildren returns direct children only`() {
        val r = backend.listChildren("/wikisource/en/Index:Foo.djvu/Pages")
        assertEquals(2, r.children.size)
        assertTrue(r.children.all { it.kind == NodeKind.file })
    }

    @Test
    fun `readContent decodes text correctly`() {
        val r = backend.readContent(
            "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1"
        )
        assertEquals("{{recto}} Page one.", r.decodeText())
        assertEquals(5003L, r.revid)
    }

    @Test
    fun `readContent throws for missing path`() {
        assertThrows(VfsBackendException::class.java) {
            backend.readContent("/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/99")
        }
    }

    @Test
    fun `writeContent succeeds and bumps revid`() {
        val path = "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1"
        val newBase64 = java.util.Base64.getEncoder().encodeToString("edited.".toByteArray())
        val result = backend.writeContent(path, newBase64, baseRevid = 5003L)
        assertEquals(WriteStatus.ok, result.status)
        assertEquals(5004L, result.newRevid)
        assertEquals("edited.", backend.readContent(path).decodeText())
    }

    @Test
    fun `writeContent returns conflict on stale base revid`() {
        val path = "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1"
        val newBase64 = java.util.Base64.getEncoder().encodeToString("edited.".toByteArray())
        val result = backend.writeContent(path, newBase64, baseRevid = 1L)
        assertEquals(WriteStatus.conflict, result.status)
        assertEquals(5003L, result.newRevid)
        // content unchanged
        assertEquals("{{recto}} Page one.", backend.readContent(path).decodeText())
    }

    @Test
    fun `writeContent returns error for missing path`() {
        val result = backend.writeContent(
            "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/99",
            java.util.Base64.getEncoder().encodeToString("x".toByteArray()),
            baseRevid = null,
        )
        assertEquals(WriteStatus.error, result.status)
    }
}
