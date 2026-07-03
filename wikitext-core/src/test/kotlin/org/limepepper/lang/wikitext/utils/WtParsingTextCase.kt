package org.limepepper.lang.wikitext.utils

import com.intellij.testFramework.ParsingTestCase
import org.limepepper.lang.wikitext.parser.WtParserDefinition
import java.io.IOException

abstract class WtParsingTextCase : ParsingTestCase(
    "simple",
    "wt",
    true,
    WtParserDefinition()
) {
    fun doTest() {
        val name = testName
        try {
            val text = loadFile("$name.$myFileExt")
            parseFile(name, text)


            val output = toParseTreeText(myFile, skipSpaces(), includeRanges())

            // @TODO want to be able to output parsing tokens
            // println(output)

            checkResult("$name.parse", myFile)
            ensureNoErrorElements()


        } catch (e: IOException) {
            throw RuntimeException(e)
        }
    }
}
