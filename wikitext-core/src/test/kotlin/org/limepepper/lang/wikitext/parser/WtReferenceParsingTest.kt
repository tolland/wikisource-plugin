package org.limepepper.lang.wikitext.parser

import com.intellij.psi.PsiErrorElement
import com.intellij.psi.util.PsiTreeUtil
import com.intellij.testFramework.ParsingTestCase
import org.limepepper.lang.wikitext.psi.WtReferenceTag
import org.limepepper.lang.wikitext.psi.WtTemplate
import org.limepepper.lang.wikitext.psi.WtInternalLink

class WtReferenceParsingTest : ParsingTestCase("", "wt", true, WtParserDefinition()) {
    override fun getTestDataPath(): String = "src/test/testData"

    private fun references(source: String): List<WtReferenceTag> {
        parseFile("references", source)
        return PsiTreeUtil.findChildrenOfType(myFile, WtReferenceTag::class.java).toList()
    }

    fun testPairedAndReusedReferencesHaveDedicatedNodes() {
        val refs = references("Before<ref name=\"thomson\" group=\"notes\">J. J. Thomson, ''Transactions'', 1885.</ref>After<ref name=\"thomson\"/>")
        assertEquals(2, refs.size)
        assertEquals("J. J. Thomson, ''Transactions'', 1885.", refs[0].referenceBody?.text)
        assertNull(refs[1].referenceBody)
        assertNull(PsiTreeUtil.findChildOfType(myFile, PsiErrorElement::class.java))
    }

    fun testReferenceContentKeepsNestedWikitext() {
        val ref = references("<ref>[[Author|Name]] {{cite|book}} <span>detail</span>\nsecond line</ref>").single()
        assertNotNull(PsiTreeUtil.findChildOfType(ref, WtTemplate::class.java))
        assertNotNull(PsiTreeUtil.findChildOfType(ref, WtInternalLink::class.java))
        assertTrue(ref.referenceBody!!.text.endsWith("second line"))
        assertNull(PsiTreeUtil.findChildOfType(myFile, PsiErrorElement::class.java))
    }

    fun testOnlyRefTagsAreReferences() {
        assertEquals(1, references("<REF>Note</REF><reference>Other</reference><nowiki><ref>literal</ref></nowiki>").size)
    }

    fun testUnclosedReferenceRetainsTypedBody() {
        val ref = references("Before<ref name=\"draft\">Unfinished note").single()
        assertEquals("Unfinished note", ref.referenceBody?.text)
        assertNotNull(PsiTreeUtil.findChildOfType(ref, PsiErrorElement::class.java))
    }
}
