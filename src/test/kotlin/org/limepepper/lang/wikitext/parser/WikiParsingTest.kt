package org.limepepper.lang.wikitext.parser

import com.intellij.psi.PsiFile
import org.limepepper.lang.wikitext.utils.WtParsingTextCase
import java.io.IOException

class WikiParsingTest : WtParsingTextCase() {
    fun testHelloWorld() = doTest(true)
    fun testNestedTemplates() = doTest(true)

    fun testParsingTestData() {
        doTestWithDump(true, true)
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

    fun doTestWithDump(checkResult: Boolean, ensureNoErrorElements: Boolean): PsiFile {
        val name = testName
        try {
            val myFile = parseFile(name, loadFile("$name.$myFileExt"))
            println(toParseTreeText(myFile, true, includeRanges()))
//            if (checkResult) {
//                checkResult(name, myFile)
//                if (ensureNoErrorElements) {
//                    ensureNoErrorElements()
//                }
//            } else {
//                toParseTreeText(myFile, skipSpaces(), includeRanges())
//            }
            return myFile
        } catch (e: IOException) {
            throw RuntimeException(e)
        }
    }

}
