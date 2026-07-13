package org.limepepper.lang.wikitext.annotation

import com.intellij.ui.JBColor
import java.awt.Color

/**
 * The box colors, cycled by the box's index in the model — shared between
 * the canvas and the editor-side anchor chrome so a box and its text anchor
 * always wear the same color.
 */
object AnnotationPalette {
    private val PALETTE = listOf(
        JBColor(Color(0x1E88E5), Color(0x64B5F6)),
        JBColor(Color(0xE53935), Color(0xEF9A9A)),
        JBColor(Color(0x43A047), Color(0xA5D6A7)),
        JBColor(Color(0xFB8C00), Color(0xFFCC80)),
        JBColor(Color(0x8E24AA), Color(0xCE93D8)),
        JBColor(Color(0x00897B), Color(0x80CBC4)),
    )

    fun colorFor(index: Int): Color = PALETTE[index % PALETTE.size]

    fun Color.withAlpha(alpha: Int) = Color(red, green, blue, alpha)
}
