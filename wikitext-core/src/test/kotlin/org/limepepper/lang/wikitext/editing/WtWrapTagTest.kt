package org.limepepper.lang.wikitext.editing

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Consistency checks on the catalog itself. It is a hand-maintained table that
 * several features read, so the cheap invariants are worth asserting rather
 * than discovering as a broken popup.
 */
class WtWrapTagTest {

    @Test
    fun idsAreUniqueAndLookupable() {
        val ids = WtWrapTag.entries.map { it.id }
        assertEquals(ids.size, ids.toSet().size, "duplicate ids in the catalog")
        for (tag in WtWrapTag.entries) {
            assertEquals(tag, WtWrapTag.byId(tag.id))
        }
    }

    @Test
    fun unknownIdIsNullRatherThanAGuess() {
        assertEquals(null, WtWrapTag.byId("no-such-tag"))
    }

    @Test
    fun onlyTagsWithAPromptCarryTheVariablePlaceholder() {
        for (tag in WtWrapTag.entries) {
            val usesPlaceholder = WtWrapTag.VARIABLE in tag.prefix || WtWrapTag.VARIABLE in tag.suffix
            assertEquals(
                tag.hasVariable,
                usesPlaceholder,
                "${tag.id}: variablePrompt and the $ {VARIABLE} placeholder must agree",
            )
        }
    }

    @Test
    fun sectionMirrorsItsNameAcrossBothMarkers() {
        // The property the live-template surrounder depends on.
        assertTrue(WtWrapTag.VARIABLE in WtWrapTag.SECTION.prefix)
        assertTrue(WtWrapTag.VARIABLE in WtWrapTag.SECTION.suffix)
    }

    @Test
    fun everyTagHasBothMarkers() {
        for (tag in WtWrapTag.entries) {
            assertFalse(tag.prefix.isEmpty(), "${tag.id} has no prefix")
            assertFalse(tag.suffix.isEmpty(), "${tag.id} has no suffix")
        }
    }

    @Test
    fun curatedSetsOnlyReferenceRealCatalogEntries() {
        // Trivially true through the type system today; the assertion is that
        // the sets stay non-empty and duplicate-free as entries come and go.
        for (set in listOf(WtWrapTagSets.surroundWith, WtWrapTagSets.toggleable)) {
            assertTrue(set.isNotEmpty())
            assertEquals(set.size, set.toSet().size, "duplicate entry in a curated set")
        }
    }
}
