package org.limepepper.lang.wikitext.parser

import com.intellij.psi.PsiFile
import org.limepepper.lang.wikitext.utils.WtParsingTextCase
import java.io.IOException
import java.io.FileNotFoundException

class WikiParsingTest : WtParsingTextCase() {
    fun testHelloWorld() = doTest()
    fun testNestedTemplates() = doTest()
    fun testWikiLinksSimple() = doTest()

    // tables
    fun testWikiTableLeadingChars() = doTest()
    fun testWikiTableSimple() = doTest()
    fun testTableWithMathTag() = doTest()

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

    fun testNestNestedParsing() {
        val content = """
            {{ph|class=_test|{{sc|nest this in a another template}}}}

        """.trimIndent()
        val myFile = parseFile(
            "randomFile",
            content
        )
        println(toParseTreeText(myFile, true, includeRanges()))
    }

    fun testSimpleTemplateParsing() {
        val content = """
            {{sc|This is rendered in small caps}}
        """.trimIndent()
        val myFile = parseFile(
            "randomFile",
            content
        )
        println(toParseTreeText(myFile, true, includeRanges()))
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
        println(toParseTreeText(myFile, true, includeRanges()))
    }

}
