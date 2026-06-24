package org.limepepper.lang.wikitext.parser

import com.intellij.testFramework.ParsingTestCase
import java.io.IOException

class WikiParsingTest : ParsingTestCase("", "wt", WtParserDefinition()) {
    fun testParsingTestData() {
        doTestWithDump(true, true)
    }

    /**
     * @return path to test data file directory relative to root of this module.
     */
    override fun getTestDataPath(): String {
        return "src/test/testData"
    }

    override fun includeRanges(): Boolean {
        return true
    }

    fun testNestNestedParsing() {
        val content = """
            document mycommand
            Source file and execute command in it
            usage:
            	check_test command/break/label.gdb
            end

            define mycommand
              break foo2
              commands
                  silent
                  printf "x is %d\n",x
                  cont
              end

              define mycommand2
                print "Custom command"
                info warranty
              end
            end

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

            break foo2
            commands
                silent
                printf "x is %d\n",x
                cont
            end

            # break on line number
            break 403
            commands
            silent
            set x = y + 4
            cont
            end

        """.trimIndent()
        val myFile = parseFile(
            "randomFile",
            content
        )
        println(toParseTreeText(myFile, true, includeRanges()))
    }

    fun doTestWithDump(checkResult: Boolean, ensureNoErrorElements: Boolean) {
        val name = getTestName()
        try {
            val myFile = parseFile(name, loadFile(name + "." + myFileExt))
            println(toParseTreeText(myFile, true, includeRanges()))
//            if (checkResult) {
//                checkResult(name, myFile)
//                if (ensureNoErrorElements) {
//                    ensureNoErrorElements()
//                }
//            } else {
//                toParseTreeText(myFile, skipSpaces(), includeRanges())
//            }
        } catch (e: IOException) {
            throw RuntimeException(e)
        }
    }

}
