package org.limepepper.lang.wikitext.highlighting

import java.awt.Color
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

class ColorUtilsTest {
    @Test
    fun `cycles distinct sentence colors in a light theme`() {
        val colors = (0 until 12).map {
            sentenceColors(it, Color(0x20, 0x20, 0x20), Color.WHITE)
        }

        assertEquals(12, colors.map { it.background.rgb }.distinct().size)
        assertEquals(colors.first(), sentenceColors(12, Color(0x20, 0x20, 0x20), Color.WHITE))
    }

    @Test
    fun `cycles distinct sentence colors in a dark theme`() {
        val colors = (0 until 12).map {
            sentenceColors(it, Color(0xEE, 0xEE, 0xEE), Color(0x20, 0x20, 0x20))
        }

        assertEquals(12, colors.map { it.background.rgb }.distinct().size)
        assertNotEquals(colors[0].foreground, colors[1].foreground)
    }

    @Test
    fun `all palette pairs retain normal text contrast`() {
        val schemes = listOf(
            Color(0x20, 0x20, 0x20) to Color.WHITE,
            Color(0xEE, 0xEE, 0xEE) to Color(0x20, 0x20, 0x20),
        )

        schemes.forEach { (foreground, background) ->
            repeat(12) { index ->
                val colors = sentenceColors(index, foreground, background)
                assertTrue(
                    contrastRatio(colors.foreground, colors.background) >= 4.5,
                    "Sentence $index has insufficient contrast",
                )
            }
        }
    }
}
