package org.limepepper.lang.wikitext.parser

import com.intellij.psi.PsiFile
import org.limepepper.lang.wikitext.utils.WtParsingTextCase
import java.io.IOException
import java.io.FileNotFoundException

class WikiParsingTest : WtParsingTextCase() {

    // math tag tests
    fun testMathTag() = doTest()

    // simple
    fun testHelloWorld() = doTest()
    fun testNestedTemplates() = doTest()
    fun testWikiLinksSimple() = doTest()

    // tables
    fun testWikiTableLeadingChars() = doTest()
    fun testWikiTableSimple() = doTest()
    fun testTableWithMathTag() = doTest()

    // headers
    fun testWikiHeaderOneWithNewline() = doTest()

    // tags
    fun testTagNoinclude01() = doTest()

    // templates
    fun testAuthorTemplate() = doTest()
    fun testProofreadpage_index_template() = doTest()
    fun testTocRowNestedTemplate() = doTest()
    fun testTemplateNestedTag01() = doTest()
    fun testTemplateNestedTag02() = doTest()

    fun testCompositeTemplateHeaders() {
        val cases = listOf(
            "{{#ifeq:{{NAMESPACE}}|Index||<br />GEOMETRY AND KINEMATICS OF MATERIAL SYSTEMS}}" to "#ifeq:{{NAMESPACE}}",
            "{{Page:Book.pdf/31}}" to "Page:Book.pdf/31",
            "{{lc:TEXT|arg1}}" to "lc:TEXT",
            "{{ {{Choose|one|two}} suffix|arg1|arg2}}" to " {{Choose|one|two}} suffix",
            "{{SOMETHING<some_tag />|arg1}}" to "SOMETHING<some_tag />",
            "{{#if:<nowiki>a|b</nowiki>|yes|no}}" to "#if:<nowiki>a|b</nowiki>",
            "{{Name<!-- hidden | }} -->&amp;|arg1}}" to "Name<!-- hidden | }} -->&amp;",
            "{{#if:<span>{{Inner|x}}</span>|yes|no}}" to "#if:<span>{{Inner|x}}</span>",
            "{{#if:[[Page|label]]|yes|no}}" to "#if:[[Page|label]]",
            "{{|arg1}}" to "",
        )
        for ((source, header) in cases) {
            parseFile("header", source)
            ensureNoErrorElements()
            val template = myFile.firstChild as org.limepepper.lang.wikitext.psi.WtTemplate
            assertEquals(header, template.templateHead?.text)
            assertEquals(source, template.text)
        }
    }

    // content model
    fun testProofread_page_1() = doTest()

    fun testParsingTestData() {
        doTest()
    }

    /**
     * @return path to the test data file directory relative to the root of this module.
     */
    override fun getTestDataPath(): String {
        return "src/test/testData"
    }

    override fun includeRanges(): Boolean {
        return true
    }

    fun testSourceTestParsing() {
        val content = """

            # Set up breakpoints for key Epub3Generator methods
            break Epub3Generator::Epub3Generator
            commands 1
                echo "\n=== Epub3Generator Constructor ===\n"
                bt
                continue
            end

            # conditional breakpoints
            break foo1
            commands
                silent
                printf "x is %d\n",x
                cont
            end

        """.trimIndent()
        val myFile = parseFile(
            "randomFile",
            content
        )
    }

}
