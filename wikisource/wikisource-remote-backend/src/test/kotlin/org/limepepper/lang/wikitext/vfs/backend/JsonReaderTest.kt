package org.limepepper.lang.wikitext.vfs.backend

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Tests for [JsonReader.array], the one part of the hand-rolled reader that
 * has to understand JSON structure rather than just find a key.
 *
 * Both cases here are real: OCR language titles routinely contain brackets
 * ("English [Latn]"), page titles and box labels can contain anything at
 * all, and the engine/model catalog is the first response with an array
 * nested inside an array element.
 */
class JsonReaderTest {

    @Test fun `brackets inside string values are data, not structure`() {
        val json = """{"items":[{"label":"a [bracketed] label"},{"label":"plain"}]}"""
        val labels = JsonReader(json).array("items") { it.string("label") }
        assertEquals(listOf("a [bracketed] label", "plain"), labels)
    }

    @Test fun `braces inside string values do not truncate the array`() {
        val json = """{"items":[{"label":"{{Template}}"},{"label":"second"}]}"""
        val labels = JsonReader(json).array("items") { it.string("label") }
        assertEquals(listOf("{{Template}}", "second"), labels)
    }

    @Test fun `an escaped quote does not end the string`() {
        val json = """{"items":[{"label":"say \"[hi]\""},{"label":"second"}]}"""
        val labels = JsonReader(json).array("items") { it.string("label") }
        assertEquals(2, labels.size)
        assertEquals("second", labels[1])
    }

    @Test fun `elements may contain nested arrays`() {
        val json = """
            {"engines":[
                {"engine":"tesseract","models":[{"code":"en"},{"code":"de"}]},
                {"engine":"pix2tex","models":[]}
            ]}
        """.trimIndent()
        val engines = JsonReader(json).array("engines") { engine ->
            engine.string("engine") to engine.array("models") { it.string("code") }
        }
        assertEquals(
            listOf("tesseract" to listOf("en", "de"), "pix2tex" to emptyList()),
            engines,
        )
    }

    @Test fun `a missing key yields an empty list`() {
        assertEquals(emptyList<String>(), JsonReader("""{"other":1}""").array("items") { "x" })
    }
}
