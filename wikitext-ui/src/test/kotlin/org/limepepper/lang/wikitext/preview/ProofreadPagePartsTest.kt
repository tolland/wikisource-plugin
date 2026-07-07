package org.limepepper.lang.wikitext.preview

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ProofreadPagePartsTest {

    private val sample = "<noinclude><pagequality level=\"1\" user=\"Admin\" /></noinclude>" +
        "== References ==\n\nNHS England. 2025a." +
        "<noinclude>{{rh||5|}}</noinclude>"

    @Test
    fun decomposesTheStandardPage() {
        val parts = ProofreadPageParts.decompose(sample)
        assertEquals(
            ProofreadPageParts(
                header = "<pagequality level=\"1\" user=\"Admin\" />",
                body = "== References ==\n\nNHS England. 2025a.",
                footer = "{{rh||5|}}",
            ),
            parts,
        )
    }

    @Test
    fun roundTripsSerializedForm() {
        val parts = ProofreadPageParts.decompose(sample)!!
        assertEquals(sample, parts.compose())
    }

    @Test
    fun composeMatchesTheWireShape() {
        val parts = ProofreadPageParts(header = "H", body = "B", footer = "F")
        assertEquals("<noinclude>H</noinclude>B<noinclude>F</noinclude>", parts.compose())
    }

    @Test
    fun handlesEmptyHeaderBodyAndFooter() {
        val text = "<noinclude></noinclude><noinclude></noinclude>"
        val parts = ProofreadPageParts.decompose(text)
        assertEquals(ProofreadPageParts("", "", ""), parts)
        assertEquals(text, parts!!.compose())
    }

    @Test
    fun bodyMayContainMultipleParagraphs() {
        val text = "<noinclude>hdr</noinclude>line one\n\nline two\n\nline three<noinclude>ftr</noinclude>"
        val parts = ProofreadPageParts.decompose(text)!!
        assertEquals("line one\n\nline two\n\nline three", parts.body)
        assertEquals(text, parts.compose())
    }

    @Test
    fun rejectsEmptyText() {
        assertNull(ProofreadPageParts.decompose(""))
    }

    @Test
    fun rejectsTextWithoutTwoNoincludeSections() {
        assertNull(ProofreadPageParts.decompose("just some plain wikitext"))
        assertNull(ProofreadPageParts.decompose("<noinclude>only one</noinclude>body"))
    }

    @Test
    fun rejectsUnbalancedTags() {
        // Three opens, two closes -> not round-trippable.
        assertNull(
            ProofreadPageParts.decompose(
                "<noinclude>a</noinclude>b<noinclude>c<noinclude>d</noinclude>",
            ),
        )
    }

    @Test
    fun rejectsLegacyV1DivLayout() {
        // The V1 layout wraps the header in <div class="pagetext">; the closing
        // </div> lives outside the three fields, so we decline to edit it in
        // structured mode rather than lose the tag on round trip.
        val v1 = "<noinclude><div class=\"pagetext\">hdr</div></noinclude>" +
            "body<noinclude>ftr</noinclude>"
        assertNull(ProofreadPageParts.decompose(v1))
    }
}
