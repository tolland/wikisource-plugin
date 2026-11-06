package org.limepepper.lang.wikitext.highlighting

import com.intellij.openapi.editor.colors.EditorColorsScheme
import com.intellij.openapi.editor.markup.TextAttributes

/** Presentation policy for an ordered band. Null leaves that band unhighlighted. */
fun interface SentenceBandHighlightingStrategy {
    fun attributes(bandIndex: Int, scheme: EditorColorsScheme): TextAttributes?
}

/** A faint tint that leaves syntax foreground colours and font styles intact. */
class QuietSentenceBandHighlighting(
    private val backgroundStrength: Double = 0.12,
) : SentenceBandHighlightingStrategy {
    init {
        require(backgroundStrength in 0.0..1.0) { "Background strength must be between 0 and 1" }
    }

    override fun attributes(bandIndex: Int, scheme: EditorColorsScheme): TextAttributes? {
        if (backgroundStrength == 0.0) return null
        val colors = sentenceColors(
            bandIndex, scheme.defaultForeground, scheme.defaultBackground, backgroundStrength,
        )
        return TextAttributes().apply { backgroundColor = colors.background }
    }
}
