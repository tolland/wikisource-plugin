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

    @Test
    fun `annotations round trip - save list delete`() {
        val path = "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1"
        val annotation = PageAnnotation(
            id = "a1", x = 10.0, y = 20.0, width = 30.0, height = 40.0,
            label = "l", category = "paragraph",
        )
        backend.saveAnnotation(path, annotation)
        assertEquals(listOf(annotation), backend.listAnnotations(path))

        backend.saveAnnotation(path, annotation.copy(x = 99.0))
        assertEquals(99.0, backend.listAnnotations(path).single().x, 0.0)

        backend.deleteAnnotation(path, "a1")
        assertEquals(emptyList<PageAnnotation>(), backend.listAnnotations(path))
    }

    @Test
    fun `text anchors are independent of boxes`() {
        val path = "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1"
        val anchor = PageTextAnchor(annotationId = "a1", textStart = 5, textEnd = 9, anchorRevid = 42L)
        backend.saveTextAnchor(path, anchor)

        // No box for a1 — the text-first workflow is legitimate.
        assertEquals(emptyList<PageAnnotation>(), backend.listAnnotations(path))
        assertEquals(listOf(anchor), backend.listTextAnchors(path))

        backend.deleteTextAnchor(path, "a1")
        assertEquals(emptyList<PageTextAnchor>(), backend.listTextAnchors(path))
        assertThrows(VfsBackendException::class.java) {
            backend.deleteTextAnchor(path, "a1")
        }
    }

    @Test
    fun `deleting a box also drops its text anchor`() {
        val path = "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1"
        backend.saveAnnotation(path, PageAnnotation(id = "a1", x = 0.0, y = 0.0, width = 1.0, height = 1.0))
        backend.saveTextAnchor(path, PageTextAnchor(annotationId = "a1", textStart = 0, textEnd = 3))

        backend.deleteAnnotation(path, "a1")
        assertEquals(emptyList<PageTextAnchor>(), backend.listTextAnchors(path))
    }

    @Test
    fun `box links round trip and require an existing range`() {
        val path = "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1"
        backend.saveAnnotation(path, PageAnnotation(id = "b1", x = 0.0, y = 0.0, width = 1.0, height = 1.0))
        assertThrows(VfsBackendException::class.java) {
            backend.saveBoxLink(path, PageBoxLink(boxId = "b1", rangeId = "missing"))
        }

        backend.saveTextAnchor(path, PageTextAnchor(annotationId = "r1", textStart = 0, textEnd = 3))
        backend.saveTextAnchor(path, PageTextAnchor(annotationId = "r2", textStart = 5, textEnd = 9))
        val link = PageBoxLink(boxId = "b1", rangeId = "r1")
        backend.saveBoxLink(path, link)
        assertEquals(listOf(link), backend.listBoxLinks(path))

        // Re-linking repoints the box's single link.
        backend.saveBoxLink(path, link.copy(rangeId = "r2"))
        assertEquals("r2", backend.listBoxLinks(path).single().rangeId)

        backend.deleteBoxLink(path, "b1")
        assertEquals(emptyList<PageBoxLink>(), backend.listBoxLinks(path))
        assertThrows(VfsBackendException::class.java) {
            backend.deleteBoxLink(path, "b1")
        }
    }

    @Test
    fun `deleting either endpoint drops the link`() {
        val path = "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1"
        backend.saveAnnotation(path, PageAnnotation(id = "b1", x = 0.0, y = 0.0, width = 1.0, height = 1.0))
        backend.saveTextAnchor(path, PageTextAnchor(annotationId = "r1", textStart = 0, textEnd = 3))
        backend.saveBoxLink(path, PageBoxLink(boxId = "b1", rangeId = "r1"))

        backend.deleteTextAnchor(path, "r1")
        assertEquals(emptyList<PageBoxLink>(), backend.listBoxLinks(path))

        backend.saveTextAnchor(path, PageTextAnchor(annotationId = "r1", textStart = 0, textEnd = 3))
        backend.saveBoxLink(path, PageBoxLink(boxId = "b1", rangeId = "r1"))
        backend.deleteAnnotation(path, "b1")
        assertEquals(emptyList<PageBoxLink>(), backend.listBoxLinks(path))
    }

    @Test
    fun `ocr run resolves the backend and echoes decodable text`() {
        val path = "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1"
        val result = backend.runOcr(path, OcrRunRequest(annotationId = "b1"))
        assertEquals("fake-ocr", result.backend)
        assertEquals("OCR of b1", result.decodeText())
        assertEquals("b1", backend.ocrRequests.single().second.annotationId)

        assertThrows(VfsBackendException::class.java) {
            backend.runOcr(path, OcrRunRequest(backend = "nope"))
        }
    }

    @Test
    fun `ocr models are advertised per backend`() {
        val path = "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1"
        val catalog = backend.listOcrModels(path)
        assertEquals("fake-ocr", catalog.backend)
        assertNull(catalog.error)
        assertEquals(listOf("tesseract", "google", "pix2tex"), catalog.engines.map { it.engine })
        assertEquals(listOf("en", "de", "fr"), catalog.engine("tesseract")!!.models.map { it.code })
        // An engine with no language dimension, not a discovery failure.
        assertTrue(catalog.engine("pix2tex")!!.models.isEmpty())

        assertThrows(VfsBackendException::class.java) {
            backend.listOcrModels(path, "nope")
        }
    }

    @Test
    fun `ocr discovery failure is reported as data, not an exception`() {
        backend.ocrCatalogError = "discovery failed: refused"
        val catalog = backend.listOcrModels("/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1")
        assertTrue(catalog.engines.isEmpty())
        assertEquals("discovery failed: refused", catalog.error)
    }

    @Test
    fun `deleting an unknown annotation throws`() {
        assertThrows(VfsBackendException::class.java) {
            backend.deleteAnnotation("/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1", "nope")
        }
    }
}
