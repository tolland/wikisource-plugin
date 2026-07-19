package org.limepepper.lang.wikitext.editor.prp

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ProofreadPagePartsTest {

    private val sample = "<noinclude><pagequality level=\"1\" user=\"Admin\" /></noinclude>" +
        "== References ==\n\nNHS England. 2025a." +
        "<noinclude>{{rh||5|}}</noinclude>"

    // A page with both a pagequality tag and a running header in the first
    // <noinclude>, and an empty footer.
    private val fullSample = "<noinclude><pagequality level=\"1\" user=\"Admin\" />{{rh|xii||Preface||}}</noinclude>" +
        "in the sort of added depth and dimension that only binocular vision affords;\n" +
        "Wittgenstein's pragmatism." +
        "<noinclude></noinclude>"

    @Test
    fun decomposesTheStandardPage() {
        val parts = ProofreadPageParts.decompose(sample)
        assertEquals(
            ProofreadPageParts(
                header = ProofreadPageHeader(PageQuality(level = 1, user = "Admin"), ""),
                body = "== References ==\n\nNHS England. 2025a.",
                footer = "{{rh||5|}}",
            ),
            parts,
        )
    }

    @Test
    fun extractsPagequalityAndHeaderRemainder() {
        val parts = ProofreadPageParts.decompose(fullSample)!!
        assertEquals(PageQuality(level = 1, user = "Admin"), parts.header.quality)
        assertEquals("{{rh|xii||Preface||}}", parts.header.text)
        assertEquals("", parts.footer)
    }

    @Test
    fun roundTripsSerializedForm() {
        assertEquals(sample, ProofreadPageParts.decompose(sample)!!.compose())
        assertEquals(fullSample, ProofreadPageParts.decompose(fullSample)!!.compose())
    }

    @Test
    fun composeMatchesTheWireShape() {
        val parts = ProofreadPageParts(
            header = ProofreadPageHeader(quality = null, text = "H"),
            body = "B",
            footer = "F",
        )
        assertEquals("<noinclude>H</noinclude>B<noinclude>F</noinclude>", parts.compose())
    }

    @Test
    fun composesQualityTagBackIntoHeader() {
        val parts = ProofreadPageParts(
            header = ProofreadPageHeader(PageQuality(level = 3, user = "Alice"), "{{rh|2|TITLE|}}"),
            body = "B",
            footer = "",
        )
        assertEquals(
            "<noinclude><pagequality level=\"3\" user=\"Alice\" />{{rh|2|TITLE|}}</noinclude>" +
                "B<noinclude></noinclude>",
            parts.compose(),
        )
    }

    @Test
    fun newPageGeneratesTheEmptySkeleton() {
        assertEquals(
            "<noinclude><pagequality level=\"1\" user=\"Admin\" /></noinclude>" +
                "<noinclude></noinclude>",
            ProofreadPageParts.newPage("Admin").compose(),
        )
        assertEquals(
            "<noinclude><pagequality level=\"3\" user=\"Bob\" /></noinclude>" +
                "<noinclude></noinclude>",
            ProofreadPageParts.newPage("Bob", PageQuality.PROOFREAD).compose(),
        )
    }

    @Test
    fun headerWithoutQualityTagIsKeptVerbatim() {
        val text = "<noinclude>{{rh|xii||Preface||}}</noinclude>body<noinclude></noinclude>"
        val parts = ProofreadPageParts.decompose(text)!!
        assertNull(parts.header.quality)
        assertEquals("{{rh|xii||Preface||}}", parts.header.text)
        assertEquals(text, parts.compose())
    }

    @Test
    fun qualityTagNotAtHeaderStartStaysInText() {
        // pywikibot would silently drop the prefix here; we keep the whole
        // section as opaque text so the round trip stays lossless.
        val header = "x<pagequality level=\"1\" user=\"Admin\" />"
        val parsed = ProofreadPageHeader.parse(header)
        assertNull(parsed.quality)
        assertEquals(header, parsed.text)
        assertEquals(header, parsed.compose())
    }

    @Test
    fun handlesEmptyHeaderBodyAndFooter() {
        val text = "<noinclude></noinclude><noinclude></noinclude>"
        val parts = ProofreadPageParts.decompose(text)
        assertEquals(
            ProofreadPageParts(ProofreadPageHeader(quality = null, text = ""), "", ""),
            parts,
        )
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
        val v1 = "<noinclude><pagequality level=\"1\" user=\"Admin\" /><div class=\"pagetext\">hdr</div></noinclude>" +
            "body<noinclude>ftr</noinclude>"
        assertNull(ProofreadPageParts.decompose(v1))
    }
}
