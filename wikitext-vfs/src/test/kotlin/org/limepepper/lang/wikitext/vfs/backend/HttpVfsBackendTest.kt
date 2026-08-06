package org.limepepper.lang.wikitext.vfs.backend

import com.sun.net.httpserver.HttpServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.io.IOException
import java.net.InetSocketAddress
import java.util.Base64

/**
 * Tests [HttpVfsBackend] against an in-process stub HTTP server using the JDK
 * com.sun.net.httpserver — no extra dependencies.
 *
 * Each test registers a handler that returns a canned JSON response, then
 * calls the backend and asserts on the parsed result.
 */
class HttpVfsBackendTest {

    private lateinit var server: HttpServer
    private lateinit var backend: HttpVfsBackend

    @Before fun setUp() {
        server = HttpServer.create(InetSocketAddress(0), 0)
        server.start()
        backend = HttpVfsBackend("http://127.0.0.1:${server.address.port}")
    }

    @After fun tearDown() {
        server.stop(0)
    }

    private fun handle(path: String, json: String) {
        server.createContext(path) { ex ->
            val body = json.toByteArray()
            ex.sendResponseHeaders(200, body.size.toLong())
            ex.responseBody.use { it.write(body) }
        }
    }

    @Test fun `stat parses directory response`() {
        handle("/vfs/stat", """
            {"path":"/wikisource/en","exists":true,"kind":"directory",
             "stable_id":42,"revid":null,"length":null,"timestamp":null,"writable":false}
        """.trimIndent())

        val r = backend.stat("/wikisource/en")
        assertTrue(r.exists)
        assertEquals(NodeKind.directory, r.kind)
        assertEquals(42L, r.stableId)
        assertNull(r.revid)
    }

    @Test fun `stat parses file response with length`() {
        handle("/vfs/stat", """
            {"path":"/wikisource/en/Index:Foo/Pages/Page:Foo/1","exists":true,"kind":"file",
             "stable_id":1003,"revid":5003,"length":19,"timestamp":"1700000000000","writable":true}
        """.trimIndent())

        val r = backend.stat("/wikisource/en/Index:Foo/Pages/Page:Foo/1")
        assertEquals(NodeKind.file, r.kind)
        assertEquals(5003L, r.revid)
        assertEquals(19L, r.length)
        assertEquals("1700000000000", r.timestamp)
        assertTrue(r.writable)
    }

    @Test fun `stat parses exists=false`() {
        handle("/vfs/stat", """{"path":"/wikisource/en/Index:No","exists":false}""")
        val r = backend.stat("/wikisource/en/Index:No")
        assertFalse(r.exists)
        assertNull(r.kind)
    }

    @Test fun `statBulk parses results array in order`() {
        handle("/vfs/stat/bulk", """
            {"results":[
              {"path":"/wikisource/en/Index:Foo/Pages/Page:Foo/1","exists":true,"kind":"file",
               "stable_id":1003,"revid":5003,"length":19,"timestamp":null,"writable":false},
              {"path":"/wikisource/en/Index:Missing","exists":false}
            ]}
        """.trimIndent())

        val r = backend.statBulk(listOf(
            "/wikisource/en/Index:Foo/Pages/Page:Foo/1",
            "/wikisource/en/Index:Missing",
        ))
        assertEquals(2, r.size)
        assertTrue(r[0].exists)
        assertEquals(5003L, r[0].revid)
        assertFalse(r[1].exists)
    }

    @Test fun `statBulk with empty input does not call the backend`() {
        assertEquals(emptyList<StatResult>(), backend.statBulk(emptyList()))
    }

    @Test fun `listChildren parses children array`() {
        handle("/vfs/children", """
            {"parent_path":"/wikisource/en/Index:Foo.djvu/Pages","children":[
              {"path":"/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1",
               "name":"Page:Foo.djvu/1","kind":"file","stable_id":1003,"revid":5003,
               "length":19,"timestamp":null,"writable":true},
              {"path":"/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/2",
               "name":"Page:Foo.djvu/2","kind":"file","stable_id":1004,"revid":5004,
               "length":20,"timestamp":null,"writable":true}
            ]}
        """.trimIndent())

        val r = backend.listChildren("/wikisource/en/Index:Foo.djvu/Pages")
        assertEquals(2, r.children.size)
        assertEquals("Page:Foo.djvu/1", r.children[0].name)
        assertEquals(NodeKind.file, r.children[0].kind)
        assertEquals(1003L, r.children[0].stableId)
    }

    @Test fun `listChildren handles empty array`() {
        handle("/vfs/children", """{"parent_path":"/wikisource/en/Index:Foo/Templates","children":[]}""")
        val r = backend.listChildren("/wikisource/en/Index:Foo/Templates")
        assertEquals(emptyList<ChildNode>(), r.children)
    }

    @Test fun `readContent decodes base64 text`() {
        val encoded = Base64.getEncoder().encodeToString("{{recto}} Page one.".toByteArray())
        handle("/vfs/content", """{"path":"/some/path","revid":5003,"content_base64":"$encoded"}""")

        val r = backend.readContent("/some/path")
        assertEquals("{{recto}} Page one.", r.decodeText())
        assertEquals(5003L, r.revid)
    }

    @Test fun `renderPreview decodes base64 html and optional server fields`() {
        val html = """<div class="mw-parser-output"><p>Hello <b>world</b></p></div>"""
        val encoded = Base64.getEncoder().encodeToString(html.toByteArray())
        handle(
            "/preview/render",
            """{"title":"Page:Foo.djvu/1","html_base64":"$encoded",
               "server":"https://en.wikisource.org","script_path":"/w"}""",
        )

        val r = backend.renderPreview(
            path = "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1",
            title = null,
            wikitext = "Hello '''world'''",
        )
        assertEquals("Page:Foo.djvu/1", r.title)
        assertEquals(html, r.decodeHtml())
        assertEquals("https://en.wikisource.org", r.server)
        assertEquals("/w", r.scriptPath)
    }

    @Test fun `renderPreview tolerates null server fields`() {
        val encoded = Base64.getEncoder().encodeToString("<p>x</p>".toByteArray())
        handle(
            "/preview/render",
            """{"title":"Scratch","html_base64":"$encoded","server":null,"script_path":null}""",
        )

        val r = backend.renderPreview(path = null, title = "Scratch", wikitext = "x")
        assertNull(r.server)
        assertNull(r.scriptPath)
    }

    @Test fun `referenceImageUrl points at the sidecar with the path url-encoded`() {
        val url = backend.referenceImageUrl(
            path = "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1",
            title = null,
        )
        assertEquals(
            "http://127.0.0.1:${server.address.port}/reference-image" +
                "?path=%2Fwikisource%2Fen%2FIndex%3AFoo.djvu%2FPages%2FPage%3AFoo.djvu%2F1",
            url,
        )
    }

    @Test fun `referenceImageUrl with bare title`() {
        val url = backend.referenceImageUrl(path = null, title = "Page:Foo.djvu/1")
        assertEquals(
            "http://127.0.0.1:${server.address.port}/reference-image?title=Page%3AFoo.djvu%2F1",
            url,
        )
    }

    @Test fun `listAnnotations parses boxes with categories`() {
        handle("/pages/annotations", """
            {"annotations":[
              {"id":"a1","x":10.5,"y":20.0,"width":30.0,"height":40.25,
               "label":"para 1","category":"paragraph"},
              {"id":"a2","x":450.0,"y":375.0,"width":100.0,"height":50.0,
               "label":null,"category":null}
            ]}
        """.trimIndent())

        val r = backend.listAnnotations("/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1")
        assertEquals(2, r.size)
        val a1 = r[0]
        assertEquals("a1", a1.id)
        assertEquals(10.5, a1.x, 0.0)
        assertEquals(40.25, a1.height, 0.0)
        assertEquals("para 1", a1.label)
        assertEquals("paragraph", a1.category)
        assertNull(r[1].label)
        assertNull(r[1].category)
    }

    @Test fun `saveAnnotation PUTs geometry and category and parses the echo`() {
        var captured: String? = null
        var requestPath: String? = null
        server.createContext("/pages/annotations/") { ex ->
            captured = ex.requestBody.readBytes().decodeToString()
            requestPath = ex.requestURI.toString()
            val body = """{"id":"a1","x":1.0,"y":2.0,"width":3.0,"height":4.0,
                           "label":"l","category":"body"}""".toByteArray()
            ex.sendResponseHeaders(200, body.size.toLong())
            ex.responseBody.use { it.write(body) }
        }

        val saved = backend.saveAnnotation(
            "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1",
            PageAnnotation(id = "a1", x = 1.0, y = 2.0, width = 3.0, height = 4.0,
                label = "l", category = "body"),
        )
        assertEquals("body", saved.category)
        assertTrue(requestPath!!.startsWith("/pages/annotations/a1?path="))
        val body = captured!!
        assertTrue(body.contains("\"x\":1.0"))
        assertTrue(body.contains("\"category\":\"body\""))
    }

    @Test fun `deleteAnnotation throws on 404`() {
        server.createContext("/pages/annotations/") { ex ->
            val body = """{"detail":"no annotation a9"}""".toByteArray()
            ex.sendResponseHeaders(404, body.size.toLong())
            ex.responseBody.use { it.write(body) }
        }
        assertThrows(VfsBackendException::class.java) {
            backend.deleteAnnotation("/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1", "a9")
        }
    }

    @Test fun `listTextAnchors parses anchors`() {
        handle("/pages/text-anchors", """
            {"anchors":[
              {"annotation_id":"a1","text_start":5,"text_end":9,"anchor_revid":42},
              {"annotation_id":"a2","text_start":7,"text_end":7,"anchor_revid":null}
            ]}
        """.trimIndent())

        val r = backend.listTextAnchors("/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1")
        assertEquals(2, r.size)
        assertEquals("a1", r[0].annotationId)
        assertEquals(5, r[0].textStart)
        assertEquals(9, r[0].textEnd)
        assertEquals(42L, r[0].anchorRevid)
        assertEquals(7, r[1].textStart)
        assertNull(r[1].anchorRevid)
    }

    @Test fun `saveTextAnchor PUTs offsets and parses the echo`() {
        var captured: String? = null
        var requestPath: String? = null
        server.createContext("/pages/text-anchors/") { ex ->
            captured = ex.requestBody.readBytes().decodeToString()
            requestPath = ex.requestURI.toString()
            val body = """{"annotation_id":"a1","text_start":0,"text_end":7,"anchor_revid":42}""".toByteArray()
            ex.sendResponseHeaders(200, body.size.toLong())
            ex.responseBody.use { it.write(body) }
        }

        val saved = backend.saveTextAnchor(
            "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1",
            PageTextAnchor(annotationId = "a1", textStart = 0, textEnd = 7, anchorRevid = 42L),
        )
        assertEquals(7, saved.textEnd)
        assertTrue(requestPath!!.startsWith("/pages/text-anchors/a1?path="))
        val body = captured!!
        assertTrue(body.contains("\"text_start\":0"))
        assertTrue(body.contains("\"anchor_revid\":42"))
    }

    @Test fun `deleteTextAnchor throws on 404`() {
        server.createContext("/pages/text-anchors/") { ex ->
            val body = """{"detail":"no text anchor a9"}""".toByteArray()
            ex.sendResponseHeaders(404, body.size.toLong())
            ex.responseBody.use { it.write(body) }
        }
        assertThrows(VfsBackendException::class.java) {
            backend.deleteTextAnchor("/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1", "a9")
        }
    }

    @Test fun `listBoxLinks parses links`() {
        handle("/pages/box-links", """
            {"links":[
              {"box_annotation_id":"b1","range_annotation_id":"r1"},
              {"box_annotation_id":"b2","range_annotation_id":"r1"}
            ]}
        """.trimIndent())

        val r = backend.listBoxLinks("/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1")
        assertEquals(2, r.size)
        assertEquals("b1", r[0].boxId)
        assertEquals("r1", r[0].rangeId)
        assertEquals("b2", r[1].boxId)
    }

    @Test fun `saveBoxLink PUTs the range id and parses the echo`() {
        var captured: String? = null
        var requestPath: String? = null
        server.createContext("/pages/box-links/") { ex ->
            captured = ex.requestBody.readBytes().decodeToString()
            requestPath = ex.requestURI.toString()
            val body = """{"box_annotation_id":"b1","range_annotation_id":"r1"}""".toByteArray()
            ex.sendResponseHeaders(200, body.size.toLong())
            ex.responseBody.use { it.write(body) }
        }

        val saved = backend.saveBoxLink(
            "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1",
            PageBoxLink(boxId = "b1", rangeId = "r1"),
        )
        assertEquals("r1", saved.rangeId)
        assertTrue(requestPath!!.startsWith("/pages/box-links/b1?path="))
        assertTrue(captured!!.contains("\"range_annotation_id\":\"r1\""))
    }

    @Test fun `deleteBoxLink throws on 404`() {
        server.createContext("/pages/box-links/") { ex ->
            val body = """{"detail":"no box link b9"}""".toByteArray()
            ex.sendResponseHeaders(404, body.size.toLong())
            ex.responseBody.use { it.write(body) }
        }
        assertThrows(VfsBackendException::class.java) {
            backend.deleteBoxLink("/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1", "b9")
        }
    }

    @Test fun `listOcrBackends parses capabilities`() {
        handle("/pages/ocr/backends", """
            {"backends":[
              {"name":"wmocr","kind":"wikimedia","base_url":"https://ocr.wiki.lan",
               "default_engine":"tesseract","default_langs":["en","de"],
               "default_prompt":null,"enabled":true,
               "supports_prompt":false,"supports_segment":false},
              {"name":"gemini","kind":"token_api","base_url":"https://api.example",
               "default_engine":null,"default_langs":[],
               "default_prompt":"latex please","enabled":true,
               "supports_prompt":true,"supports_segment":true}
            ]}
        """.trimIndent())

        val r = backend.listOcrBackends("/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1")
        assertEquals(2, r.size)
        assertEquals("wmocr", r[0].name)
        assertEquals(listOf("en", "de"), r[0].defaultLangs)
        assertTrue(r[1].supportsPrompt)
        assertEquals("latex please", r[1].defaultPrompt)
    }

    @Test fun `runOcr POSTs the request and decodes the text`() {
        var captured: String? = null
        server.createContext("/pages/ocr/run") { ex ->
            captured = ex.requestBody.readBytes().decodeToString()
            // "line one\nline two" base64-encoded
            val body = """{"backend":"gemini","kind":"token_api","engine":null,
                           "text":"ignored","text_base64":"bGluZSBvbmUKbGluZSB0d28="}""".toByteArray()
            ex.sendResponseHeaders(200, body.size.toLong())
            ex.responseBody.use { it.write(body) }
        }

        val result = backend.runOcr(
            "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1",
            OcrRunRequest(
                backend = "gemini",
                annotationId = "b1",
                boxX = 1.0, boxY = 2.0, boxWidth = 3.0, boxHeight = 4.0,
                imageBase64 = "aGVsbG8=",
                langs = listOf("en"),
                prompt = "latex",
            ),
        )
        assertEquals("line one\nline two", result.decodeText())
        val body = captured!!
        assertTrue(body.contains("\"backend\":\"gemini\""))
        assertTrue(body.contains("\"image_base64\":\"aGVsbG8=\""))
        assertTrue(body.contains("\"prompt\":\"latex\""))
        assertTrue(body.contains("\"langs\":[\"en\"]"))
        assertTrue(body.contains("\"box\":{\"x\":1.0,\"y\":2.0,\"width\":3.0,\"height\":4.0}"))
        assertTrue(body.contains("\"rotate\":0"))
    }

    @Test fun `listOcrModels parses nested engines and models`() {
        var query: String? = null
        server.createContext("/pages/ocr/models") { ex ->
            query = ex.requestURI.query
            // A title containing a bracket on purpose: JsonReader.array has
            // to treat it as data, not as array structure.
            val body = """{"backend":"wmocr","engines":[
                {"engine":"tesseract","models":[
                    {"code":"en","title":"English [Latn]"},
                    {"code":"de","title":"German"}]},
                {"engine":"pix2tex","models":[]}
            ],"error":null}""".toByteArray()
            ex.sendResponseHeaders(200, body.size.toLong())
            ex.responseBody.use { it.write(body) }
        }

        val catalog = backend.listOcrModels(
            "/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1",
            "wmocr",
        )
        assertEquals("wmocr", catalog.backend)
        assertNull(catalog.error)
        assertEquals(listOf("tesseract", "pix2tex"), catalog.engines.map { it.engine })
        assertEquals(2, catalog.engines[0].models.size)
        assertEquals("English [Latn]", catalog.engines[0].models[0].title)
        assertEquals("English [Latn] (en)", catalog.engines[0].models[0].displayName)
        // An engine with no language dimension, not a parse failure.
        assertTrue(catalog.engines[1].models.isEmpty())
        assertTrue(query!!.contains("backend=wmocr"))
    }

    @Test fun `listOcrModels surfaces a discovery error as data`() {
        handle("/pages/ocr/models", """
            {"backend":"wmocr","engines":[],"error":"discovery failed: refused"}
        """.trimIndent())

        val catalog = backend.listOcrModels("/wikisource/en/Index:Foo.djvu/Pages/Page:Foo.djvu/1")
        assertTrue(catalog.engines.isEmpty())
        assertEquals("discovery failed: refused", catalog.error)
    }

    @Test fun `throws VfsBackendException on HTTP error`() {
        server.createContext("/vfs/stat") { ex ->
            val body = """{"detail":"not found"}""".toByteArray()
            ex.sendResponseHeaders(404, body.size.toLong())
            ex.responseBody.use { it.write(body) }
        }
        assertThrows(VfsBackendException::class.java) {
            backend.stat("/wikisource/en/Index:Missing")
        }
    }

    @Test fun `throws VfsBackendException, not a raw ConnectException, when the sidecar is down`() {
        // Point at a port nothing is listening on instead of the running stub server.
        val unreachable = HttpVfsBackend("http://127.0.0.1:1")
        assertThrows(VfsBackendException::class.java) {
            unreachable.stat("/wikisource/en/Index:Anything")
        }
    }

    @Test fun `VfsBackendException is an IOException so VirtualFile content-read overrides propagate it correctly`() {
        assertTrue(IOException::class.java.isAssignableFrom(VfsBackendException::class.java))
    }
}
