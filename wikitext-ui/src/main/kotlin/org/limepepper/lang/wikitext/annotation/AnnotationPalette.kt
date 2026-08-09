package org.limepepper.lang.wikitext.annotation

import com.intellij.ui.JBColor
import java.awt.Color

/**
 * The box colors — shared between the canvas and the editor-side text-range
 * chrome ([org.limepepper.lang.wikitext.editor.prp.WtTextRangeManager]) so a
 * box and its linked text anchor always wear the same color.
 *
 * Colored by [AnnotationCategory], one fixed hue per category (equation is
 * always blue, ignore is always red, …), rather than by a box's position in
 * the model. Index-based cycling meant a box's color depended on draw order
 * and shifted whenever an earlier box was deleted, which is meaningless
 * noise once boxes actually carry a category — the color should say what
 * kind of region this is, consistently across the whole page and across
 * pages.
 *
 * A box with no category yet (the common case right after drawing, before
 * the user assigns one) has nothing to color it by, so it falls back to
 * cycling through the same hues by [colorFor]'s `fallbackIndex` — merely
 * distinguishable from its neighbors, not a stable identity the way a
 * category color is.
 */
object AnnotationPalette {
    private val CATEGORY_COLORS: Map<AnnotationCategory, Color> = mapOf(
        AnnotationCategory.EQUATION to JBColor(Color(0x1E88E5), Color(0x64B5F6)), // blue
        AnnotationCategory.IGNORE to JBColor(Color(0xE53935), Color(0xEF9A9A)), // red
        AnnotationCategory.BODY to JBColor(Color(0x43A047), Color(0xA5D6A7)), // green
        AnnotationCategory.HEADER to JBColor(Color(0xFB8C00), Color(0xFFCC80)), // orange
        AnnotationCategory.SECTION to JBColor(Color(0x8E24AA), Color(0xCE93D8)), // purple
        AnnotationCategory.PARAGRAPH to JBColor(Color(0x00897B), Color(0x80CBC4)), // teal
        AnnotationCategory.FOOTER to JBColor(Color(0x6D4C41), Color(0xBCAAA4)), // brown
    )

    /** Cycled for uncategorized boxes; same hues as [CATEGORY_COLORS], so nothing new to learn. */
    private val UNCATEGORIZED_CYCLE: List<Color> = CATEGORY_COLORS.values.toList()

    init {
        check(CATEGORY_COLORS.keys == AnnotationCategory.entries.toSet()) {
            "AnnotationPalette is missing a color for one of ${AnnotationCategory.entries}"
        }
    }

    /**
     * The color for a box/range: fixed for [category], or — when it is null
     * — cycled through the same palette by [fallbackIndex] so uncategorized
     * boxes on one page still read as distinct from each other.
     */
    fun colorFor(category: AnnotationCategory?, fallbackIndex: Int): Color =
        category?.let(CATEGORY_COLORS::get)
            ?: UNCATEGORIZED_CYCLE[fallbackIndex.mod(UNCATEGORIZED_CYCLE.size)]

    fun Color.withAlpha(alpha: Int) = Color(red, green, blue, alpha)
}
