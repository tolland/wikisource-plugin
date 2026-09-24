package org.limepepper.lang.wikitext.annotation

import org.limepepper.lang.wikitext.annotation.AnnotationPalette.colorFor
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals

class AnnotationPaletteTest {
    private val assigned = AnnotationCategory.entries.filter { it.isAssigned }

    @Test
    fun everyCategoryHasItsOwnColor() {
        val colors = assigned.map { colorFor(it, fallbackIndex = 0) }
        assertEquals(colors.size, colors.toSet().size, "two categories share a color")
    }

    @Test
    fun aCategorysColorIgnoresTheFallbackIndex() {
        // The whole point: a category's color is an identity, not a position.
        for (category in assigned) {
            assertEquals(colorFor(category, 0), colorFor(category, 7))
        }
    }

    @Test
    fun equationIsBlueAndIgnoreIsRed() {
        assertEquals(java.awt.Color(0x1E88E5).rgb, colorFor(AnnotationCategory.EQUATION, 0).rgb)
        assertEquals(java.awt.Color(0xE53935).rgb, colorFor(AnnotationCategory.IGNORE, 0).rgb)
    }

    @Test
    fun uncategorizedCyclesByFallbackIndex() {
        val a = colorFor(null, 0)
        val b = colorFor(null, 1)
        assertNotEquals(a, b)
    }

    @Test
    fun uncategorizedCycleWrapsAround() {
        val first = colorFor(null, 0)
        val wrapped = colorFor(null, assigned.size)
        assertEquals(first, wrapped)
    }

    @Test
    fun unknownIsColoredAsUncategorized() {
        for (index in 0..3) {
            assertEquals(colorFor(null, index), colorFor(AnnotationCategory.UNKNOWN, index))
        }
    }
}
