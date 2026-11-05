package org.limepepper.lang.wikitext.highlighting

import com.intellij.openapi.editor.colors.EditorColorsManager
import com.intellij.openapi.editor.HighlighterColors
import com.intellij.openapi.editor.markup.TextAttributes
import com.intellij.testFramework.LightPlatformTestCase
import java.awt.Color

class SentenceBandHighlightingStrategyTest : LightPlatformTestCase() {
    fun testQuietBandsOnlySetBackground() {
        val scheme = EditorColorsManager.getInstance().globalScheme.clone() as com.intellij.openapi.editor.colors.EditorColorsScheme
        for (background in listOf(Color.WHITE, Color(0x20, 0x20, 0x20))) {
            scheme.setAttributes(HighlighterColors.TEXT, TextAttributes().apply {
                foregroundColor = if (background == Color.WHITE) Color.BLACK else Color.WHITE
                backgroundColor = background
            })
            val attributes = QuietSentenceBandHighlighting().attributes(0, scheme)!!
            assertNull(attributes.foregroundColor)
            assertNull(attributes.effectColor)
            assertEquals(java.awt.Font.PLAIN, attributes.fontType)
            val tint = attributes.backgroundColor!!
            assertTrue(kotlin.math.abs(tint.red - background.red) <= 31)
            assertTrue(kotlin.math.abs(tint.green - background.green) <= 31)
            assertTrue(kotlin.math.abs(tint.blue - background.blue) <= 31)
        }
    }

    fun testZeroStrengthSkipsHighlighting() {
        assertNull(QuietSentenceBandHighlighting(0.0).attributes(
            0, EditorColorsManager.getInstance().globalScheme,
        ))
    }
}
