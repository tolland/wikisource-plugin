package org.limepepper.lang.wikitext.utils

import com.intellij.testFramework.ParsingTestCase
import org.limepepper.lang.wikitext.lexer.WtLexerAdapter
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
            dumpLexerTokensIfRequested(text)

            parseFile(name, text)


            val output = toParseTreeText(myFile, skipSpaces(), includeRanges())
            if (shouldDumpParseTree()) {
                println("==== PARSE TREE ====")
                println(output)
            }

            // @TODO want to be able to output parsing tokens
            println(output)

            ensureNoErrorElements()
            checkResult("$name.parse", myFile)


        } catch (e: IOException) {
            throw RuntimeException(e)
        }
    }

    private fun dumpLexerTokensIfRequested(text: String) {
        if (!shouldDumpLexerTokens()) return

        val tokens = LexerTestUtils.tokenizeWithAdapter(text, WtLexerAdapter())
        LexerTestUtils.printTokens(tokens)
    }

    private fun shouldDumpLexerTokens(): Boolean =
        System.getProperty("WIKITEXT_PARSER_DUMP_TOKENS")?.equals("true", ignoreCase = true) == true ||
                System.getenv("WIKITEXT_PARSER_DUMP_TOKENS")?.equals("true", ignoreCase = true) == true ||
                System.getProperty("LEXER_DEBUG")?.equals("true", ignoreCase = true) == true ||
                System.getenv("LEXER_DEBUG")?.equals("true", ignoreCase = true) == true

    private fun shouldDumpParseTree(): Boolean =
        System.getProperty("WIKITEXT_PARSER_DUMP_TREE")?.equals("true", ignoreCase = true) == true ||
                System.getenv("WIKITEXT_PARSER_DUMP_TREE")?.equals("true", ignoreCase = true) == true
}
