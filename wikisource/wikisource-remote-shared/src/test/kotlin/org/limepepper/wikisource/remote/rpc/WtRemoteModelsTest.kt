package org.limepepper.wikisource.remote.rpc

import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Test

class WtRemoteModelsTest {
    @Test
    fun testPageIdentifierSerialization() {
        val pageId = PageIdentifier("en", "Page:Test.djvu/1", 12345L)
        val json = Json.encodeToString(pageId)
        val decoded = Json.decodeFromString<PageIdentifier>(json)
        assertEquals(pageId, decoded)
    }

    @Test
    fun testPageSnapshotSerialization() {
        val snapshot = PageSnapshot(
            id = PageIdentifier("en", "Page:Test.djvu/1"),
            content = "Hello world",
            quality = 3,
            scanImageUrl = "https://example.com/test.jpg"
        )
        val json = Json.encodeToString(snapshot)
        val decoded = Json.decodeFromString<PageSnapshot>(json)
        assertEquals(snapshot, decoded)
    }

    @Test
    fun testOcrRequestResponseSerialization() {
        val req = OcrRequest(
            pageId = PageIdentifier("en", "Page:Test.djvu/1"),
            engine = "tesseract",
            boundingBox = listOf(0.1, 0.2, 0.3, 0.4)
        )
        val reqJson = Json.encodeToString(req)
        val reqDecoded = Json.decodeFromString<OcrRequest>(reqJson)
        assertEquals(req, reqDecoded)

        val resp = OcrResponse(
            pageId = PageIdentifier("en", "Page:Test.djvu/1"),
            recognizedText = "Recognized text",
            confidence = 0.95
        )
        val respJson = Json.encodeToString(resp)
        val respDecoded = Json.decodeFromString<OcrResponse>(respJson)
        assertEquals(resp, respDecoded)
    }
}
