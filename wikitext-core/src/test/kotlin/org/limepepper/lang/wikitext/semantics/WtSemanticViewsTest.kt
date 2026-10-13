package org.limepepper.lang.wikitext.semantics

import com.intellij.psi.util.PsiTreeUtil
import com.intellij.testFramework.ParsingTestCase
import org.limepepper.lang.wikitext.parser.WtParserDefinition
import org.limepepper.lang.wikitext.psi.WtHtmlTag
import org.limepepper.lang.wikitext.psi.WtTypes

class WtSemanticViewsTest : ParsingTestCase("", "wt", true, WtParserDefinition()) {
    override fun getTestDataPath(): String = "src/test/testData"

    private fun views(source: String): List<WtSemanticView> {
        parseFile("views", source)
        return PsiTreeUtil.findChildrenOfType(myFile, WtHtmlTag::class.java).mapNotNull(WtSemanticViews::of)
    }

    fun testReferenceAttributesAndRangesRemainAnchoredToGenericPsi() {
        val source = "Before<ref name='thomson' group=notes>[[Link]] {{cite|book}}</ref>After<ref name=thomson/>"
        val refs = views(source).filterIsInstance<WtReferenceView>()
        assertEquals(2, refs.size)
        val definition = refs[0]
        assertEquals(WtTypes.HTML_TAG, definition.source.node.elementType)
        assertEquals("thomson", definition.name)
        assertEquals("notes", definition.group)
        assertFalse(definition.isReuse)
        assertEquals("[[Link]] {{cite|book}}", definition.bodyRange!!.substring(source))
        val attribute = definition.tag.attribute("name")!!
        assertEquals("thomson", attribute.valueRange.substring(source))
        assertEquals("<ref name='thomson' group=notes>", definition.tag.openingRange.substring(source))
        assertEquals("</ref>", definition.tag.closingRange!!.substring(source))
        assertTrue(refs[1].isReuse)
        assertNull(refs[1].bodyRange)
    }

    fun testSectionMarkersDoNotInventNestedSpansOrErrors() {
        val markers = views("<section begin=chapter1/>One<section begin='chapter2'/>Two<section end=chapter1/>Three")
            .filterIsInstance<WtSectionMarkerView>()
        assertEquals(listOf("chapter1", "chapter2", "chapter1"), markers.map { it.name })
        assertEquals(listOf(WtSectionBoundary.BEGIN, WtSectionBoundary.BEGIN, WtSectionBoundary.END), markers.map { it.boundary })
        assertTrue(markers.all { it.tag.bodyRange == null })
        assertNull(PsiTreeUtil.findChildOfType(myFile, com.intellij.psi.PsiErrorElement::class.java))
    }

    fun testUnknownTagsAndAmbiguousMarkersStayGeneric() {
        assertEmpty(views("<span>Text</span><section/><section begin=a end=b/><nowiki><ref>literal</ref></nowiki>"))
        val tag = PsiTreeUtil.findChildrenOfType(myFile, WtHtmlTag::class.java).first()
        assertEquals("span", WtSemanticViews.tag(tag)!!.name)
    }

    fun testQuotedLabelsRetainSpacesAndEmptyValues() {
        val markers = views("<section begin=\"chapter one\"/><section end=\"\"/>").filterIsInstance<WtSectionMarkerView>()
        assertEquals(listOf("chapter one", ""), markers.map { it.name })
        assertEquals("chapter one", markers[0].label.valueRange.substring(myFile.text))
        assertTrue(markers[1].label.valueRange.isEmpty)
    }
}
