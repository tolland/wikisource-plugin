package org.limepepper.lang.wikitext.parser

import com.intellij.psi.PsiErrorElement
import com.intellij.psi.util.PsiTreeUtil
import com.intellij.testFramework.ParsingTestCase
import org.limepepper.lang.wikitext.psi.WtHtmlTag
import org.limepepper.lang.wikitext.semantics.WtSemanticViews
import org.limepepper.lang.wikitext.semantics.WtReferenceView
import org.limepepper.lang.wikitext.psi.WtTemplate
import org.limepepper.lang.wikitext.psi.WtInternalLink

class WtReferenceParsingTest : ParsingTestCase("", "wt", true, WtParserDefinition()) {
    override fun getTestDataPath(): String = "src/test/testData"

    private fun references(source: String): List<WtReferenceView> {
        parseFile("references", source)
        return PsiTreeUtil.findChildrenOfType(myFile, WtHtmlTag::class.java).mapNotNull(WtSemanticViews::reference)
    }

    fun testPairedAndReusedReferencesHaveTypedViews() {
        val refs = references("Before<ref name=\"thomson\" group=\"notes\">J. J. Thomson, ''Transactions'', 1885.</ref>After<ref name=\"thomson\"/>")
        assertEquals(2, refs.size)
        assertEquals("J. J. Thomson, ''Transactions'', 1885.", refs[0].bodyRange?.substring(myFile.text))
        assertNull(refs[1].bodyRange)
        assertNull(PsiTreeUtil.findChildOfType(myFile, PsiErrorElement::class.java))
    }

    fun testReferenceContentKeepsNestedWikitext() {
        val ref = references("<ref>[[Author|Name]] {{cite|book}} <span>detail</span>\nsecond line</ref>").single()
        assertNotNull(PsiTreeUtil.findChildOfType(ref.source, WtTemplate::class.java))
        assertNotNull(PsiTreeUtil.findChildOfType(ref.source, WtInternalLink::class.java))
        assertTrue(ref.bodyRange!!.substring(myFile.text).endsWith("second line"))
        assertNull(PsiTreeUtil.findChildOfType(myFile, PsiErrorElement::class.java))
    }

    fun testReferenceInTableCellKeepsBodyAndFollowingCells() {
        val body = "This fifth alternative is ''transitional'' and seeks to ''change'' the structure."
        val source = """
            {| class="" style="margin: auto; border: none;"
            |-
            !
            !
            ! Culture Goals
            ! Institutionalized Means
            |-
            | style="text-align: right;" | I. || Conformity || + || +
            |-
            | colspan="4" style="text-align: center;" |{{Hr}}
            |-
            | style="text-align: right;" | V. || Rebellion<ref>$body</ref> || ± || ±
            |}
        """.trimIndent()
        val ref = references(source).single()
        assertEquals(body, ref.bodyRange?.substring(source))
        assertEquals("<ref>$body</ref>", ref.source.text)
        assertNull(PsiTreeUtil.findChildOfType(myFile, PsiErrorElement::class.java))
    }

    fun testTableReferenceKeepsNestedTagsTemplatesAndLinks() {
        val body = "Note <span>detail</span> {{cite|book}} [[Author|Name]]\nsecond line"
        val source = "{|\n| <ref name=note>$body</ref><ref name=note/> || next\n|}"
        val refs = references(source)
        assertEquals(2, refs.size)
        assertEquals(body, refs[0].bodyRange?.substring(source))
        assertNotNull(PsiTreeUtil.findChildOfType(refs[0].source, WtTemplate::class.java))
        assertNotNull(PsiTreeUtil.findChildOfType(refs[0].source, WtInternalLink::class.java))
        assertNull(refs[1].bodyRange)
        assertNull(PsiTreeUtil.findChildOfType(myFile, PsiErrorElement::class.java))
    }

    fun testOnlyRefTagsAreReferences() {
        assertEquals(1, references("<REF>Note</REF><reference>Other</reference><nowiki><ref>literal</ref></nowiki>").size)
    }

    fun testUnclosedReferenceRetainsTypedBody() {
        val ref = references("Before<ref name=\"draft\">Unfinished note").single()
        assertEquals("Unfinished note", ref.bodyRange?.substring(myFile.text))
        assertNotNull(PsiTreeUtil.findChildOfType(ref.source, PsiErrorElement::class.java))
    }
}
