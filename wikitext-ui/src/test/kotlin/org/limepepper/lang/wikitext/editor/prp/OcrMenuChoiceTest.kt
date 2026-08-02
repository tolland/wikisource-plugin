package org.limepepper.lang.wikitext.editor.prp

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.limepepper.lang.wikitext.vfs.backend.OcrBackendInfo
import org.limepepper.lang.wikitext.vfs.settings.OcrFavorite

/**
 * Tests for how the "Run OCR" menu is generated. The menu is built from two
 * lists that are maintained independently — the project's favourites and
 * the backends a site happens to have configured — so the interesting cases
 * are all disagreements between them.
 */
class OcrMenuChoiceTest {

    private val wmocr = OcrBackendInfo(name = "wmocr", kind = "wikimedia", defaultEngine = "tesseract")
    private val gemini = OcrBackendInfo(name = "gemini", kind = "token_api")

    @Test fun `favourites keep their configured order`() {
        val favorites = listOf(
            OcrFavorite(engine = "tesseract", langs = listOf("en")),
            OcrFavorite(engine = "pix2tex", label = "pix2tex (LaTeX)"),
            OcrFavorite(engine = "google", langs = listOf("la")),
        )
        val choices = OcrMenuChoice.resolve(favorites, listOf(wmocr))
        assertEquals(
            listOf("tesseract · en", "pix2tex (LaTeX)", "google · la"),
            choices.map { it.label },
        )
        assertTrue(choices.all { it.backend == wmocr })
    }

    @Test fun `a favourite naming a backend the site lacks is dropped`() {
        val favorites = listOf(
            OcrFavorite(engine = "tesseract", langs = listOf("en")),
            OcrFavorite(engine = "vision", backend = "retired"),
        )
        // Dropped at build time rather than failing on click.
        val choices = OcrMenuChoice.resolve(favorites, listOf(wmocr))
        assertEquals(listOf("tesseract · en"), choices.map { it.label })
    }

    @Test fun `favourites route to the backend they pin`() {
        val favorites = listOf(
            OcrFavorite(engine = "tesseract", langs = listOf("en"), backend = "wmocr"),
            OcrFavorite(engine = "vision", backend = "gemini"),
        )
        val choices = OcrMenuChoice.resolve(favorites, listOf(wmocr, gemini))
        assertEquals(listOf(wmocr, gemini), choices.map { it.backend })
    }

    @Test fun `nothing resolves when the site has no backends`() {
        val favorites = listOf(OcrFavorite(engine = "tesseract", langs = listOf("en")))
        assertTrue(OcrMenuChoice.resolve(favorites, emptyList()).isEmpty())
    }

    @Test fun `the fallback offers each backend on its own defaults`() {
        val choices = OcrMenuChoice.defaults(listOf(wmocr, gemini))
        assertEquals(listOf("wmocr · tesseract", "gemini"), choices.map { it.label })
        // No favourite means every field stays unset for the sidecar to fill.
        assertTrue(choices.all { it.favorite == null })
    }

    @Test fun `a choice reports the engine it will run`() {
        val favorite = OcrFavorite(engine = "pix2tex")
        assertEquals("pix2tex", OcrMenuChoice.resolve(listOf(favorite), listOf(wmocr))[0].engine)
        // Without a favourite it is the backend's configured default...
        assertEquals("tesseract", OcrMenuChoice.defaults(listOf(wmocr))[0].engine)
        // ...which may itself be unset, leaving the choice to the sidecar.
        assertNull(OcrMenuChoice.defaults(listOf(gemini))[0].engine)
    }
}
