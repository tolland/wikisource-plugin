package org.limepepper.lang.wikitext.vfs.settings

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.limepepper.lang.wikitext.vfs.backend.OcrBackendInfo

/**
 * Tests for [OcrFavorite] — the settings-side half of the dynamic "Run OCR"
 * menu. The behaviour that matters is what a favourite leaves *unset*: the
 * sidecar fills engine/langs/prompt from the backend's configured defaults,
 * so sending an empty list where the user chose nothing would override
 * those defaults with "no languages" rather than deferring to them.
 */
class OcrFavoriteTest {

    private val wmocr = OcrBackendInfo(name = "wmocr", kind = "wikimedia", defaultEngine = "tesseract")
    private val gemini = OcrBackendInfo(name = "gemini", kind = "token_api", supportsPrompt = true)

    @Test fun `display name lists engine and languages`() {
        assertEquals(
            "tesseract · en, de",
            OcrFavorite(engine = "tesseract", langs = listOf("en", "de")).displayName(),
        )
    }

    @Test fun `display name omits languages when there are none`() {
        // pix2tex has no language dimension; "pix2tex · " would be noise.
        assertEquals("pix2tex", OcrFavorite(engine = "pix2tex").displayName())
    }

    @Test fun `display name names the backend only when one is pinned`() {
        assertEquals(
            "tesseract · en [wmocr]",
            OcrFavorite(engine = "tesseract", langs = listOf("en"), backend = "wmocr").displayName(),
        )
    }

    @Test fun `an explicit label wins`() {
        assertEquals(
            "Fraktur",
            OcrFavorite(engine = "tesseract", langs = listOf("deu_frak"), label = "Fraktur")
                .displayName(),
        )
    }

    @Test fun `an unpinned favourite resolves to the first backend`() {
        val favorite = OcrFavorite(engine = "tesseract")
        assertEquals(wmocr, favorite.resolveBackend(listOf(wmocr, gemini)))
        assertTrue(favorite.isRunnableWith(listOf(wmocr, gemini)))
    }

    @Test fun `a pinned favourite resolves to its own backend`() {
        val favorite = OcrFavorite(engine = "gemini-vision", backend = "gemini")
        assertEquals(gemini, favorite.resolveBackend(listOf(wmocr, gemini)))
    }

    @Test fun `a favourite pinned to a missing backend does not resolve`() {
        val favorite = OcrFavorite(engine = "tesseract", backend = "retired")
        assertNull(favorite.resolveBackend(listOf(wmocr)))
        assertFalse(favorite.isRunnableWith(listOf(wmocr)))
    }

    @Test fun `nothing resolves when the site has no backends`() {
        assertFalse(OcrFavorite(engine = "tesseract").isRunnableWith(emptyList()))
    }

    @Test fun `empty languages travel as null so backend defaults survive`() {
        val request = OcrFavorite(engine = "pix2tex").toRunRequest("wmocr")
        assertNull(request.langs)
        assertEquals("pix2tex", request.engine)
        assertNull(request.prompt)
    }

    @Test fun `chosen languages and prompt travel as given`() {
        val request = OcrFavorite(
            engine = "tesseract",
            langs = listOf("en", "la"),
            prompt = "transcribe the latex",
        ).toRunRequest("wmocr", annotationId = "b1", boxX = 1.0, boxY = 2.0)
        assertEquals(listOf("en", "la"), request.langs)
        assertEquals("transcribe the latex", request.prompt)
        assertEquals("b1", request.annotationId)
        assertEquals("wmocr", request.backend)
    }

    @Test fun `a blank prompt is not sent`() {
        assertNull(OcrFavorite(engine = "tesseract", prompt = "  ").toRunRequest("wmocr").prompt)
    }
}
