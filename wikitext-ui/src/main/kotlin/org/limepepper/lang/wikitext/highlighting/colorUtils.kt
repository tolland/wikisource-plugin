package org.limepepper.lang.wikitext.highlighting

import com.intellij.openapi.editor.colors.EditorColorsManager
import com.intellij.openapi.editor.markup.TextAttributes
import java.awt.Color
import java.awt.Font
import kotlin.math.roundToInt

private const val MINIMUM_TEXT_CONTRAST = 4.5

/*
 * Ordered so neighbouring sentences are far apart in hue. A finite palette is
 * intentional: the same sentence index always produces the same colour.
 */
private val SENTENCE_HUES = floatArrayOf(
    210f, 30f, 135f, 285f, 60f, 180f, 330f, 105f, 255f, 0f, 165f, 315f,
)

internal data class SentenceColorPair(
    val foreground: Color,
    val background: Color,
)

fun alternateSentenceAttributes(sentenceIndex: Int): TextAttributes {
    val scheme = EditorColorsManager.getInstance().globalScheme
    val colors = sentenceColors(
        sentenceIndex = sentenceIndex,
        defaultForeground = scheme.defaultForeground,
        defaultBackground = scheme.defaultBackground,
    )

    return TextAttributes(
        colors.foreground,
        colors.background,
        null,
        null,
        Font.PLAIN,
    )
}

internal fun sentenceColors(
    sentenceIndex: Int,
    defaultForeground: Color,
    defaultBackground: Color,
): SentenceColorPair {
    val hue = SENTENCE_HUES[Math.floorMod(sentenceIndex, SENTENCE_HUES.size)] / 360f
    val darkTheme = relativeLuminance(defaultBackground) < 0.35

    // These are pastel anchors adapted for each theme. Blending them with the
    // scheme colours keeps the bands quiet while still changing actual hue.
    val backgroundAnchor = if (darkTheme) {
        Color.getHSBColor(hue, 0.38f, 0.30f)
    } else {
        Color.getHSBColor(hue, 0.24f, 0.98f)
    }
    val foregroundAnchor = if (darkTheme) {
        Color.getHSBColor(hue, 0.22f, 1.00f)
    } else {
        Color.getHSBColor(hue, 0.62f, 0.28f)
    }

    val background = mix(defaultBackground, backgroundAnchor, if (darkTheme) 0.42 else 0.55)
    val tintedForeground = mix(defaultForeground, foregroundAnchor, if (darkTheme) 0.32 else 0.28)
    val foreground = ensureContrast(
        foreground = tintedForeground,
        background = background,
        preferredExtreme = if (darkTheme) Color.WHITE else Color.BLACK,
    )

    return SentenceColorPair(foreground, background)
}

internal fun contrastRatio(first: Color, second: Color): Double {
    val lighter = maxOf(relativeLuminance(first), relativeLuminance(second))
    val darker = minOf(relativeLuminance(first), relativeLuminance(second))
    return (lighter + 0.05) / (darker + 0.05)
}

private fun ensureContrast(
    foreground: Color,
    background: Color,
    preferredExtreme: Color,
): Color {
    if (contrastRatio(foreground, background) >= MINIMUM_TEXT_CONTRAST) {
        return foreground
    }

    // Binary search for the smallest correction, retaining as much hue as
    // possible while reaching WCAG AA contrast for normal-sized text.
    var lower = 0.0
    var upper = 1.0
    repeat(10) {
        val amount = (lower + upper) / 2.0
        if (contrastRatio(mix(foreground, preferredExtreme, amount), background) >=
            MINIMUM_TEXT_CONTRAST
        ) {
            upper = amount
        } else {
            lower = amount
        }
    }
    return mix(foreground, preferredExtreme, upper)
}

private fun relativeLuminance(color: Color): Double {
    fun linear(channel: Int): Double {
        val value = channel / 255.0
        return if (value <= 0.04045) {
            value / 12.92
        } else {
            Math.pow((value + 0.055) / 1.055, 2.4)
        }
    }

    return 0.2126 * linear(color.red) +
        0.7152 * linear(color.green) +
        0.0722 * linear(color.blue)
}

private fun mix(from: Color, towards: Color, amount: Double): Color {
    val fraction = amount.coerceIn(0.0, 1.0)

    fun channel(a: Int, b: Int): Int =
        (a + (b - a) * fraction)
            .roundToInt()
            .coerceIn(0, 255)

    return Color(
        channel(from.red, towards.red),
        channel(from.green, towards.green),
        channel(from.blue, towards.blue),
        from.alpha,
    )
}
