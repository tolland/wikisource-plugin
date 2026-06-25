package org.limepepper.lang.wikitext.utils

import com.intellij.lexer.Lexer
import com.intellij.openapi.util.io.FileUtil
import com.intellij.psi.TokenType
import com.intellij.testFramework.LexerTestCase
import org.limepepper.lang.wikitext.lexer.WtLexer
import org.limepepper.lang.wikitext.lexer.WtLexerAdapter
import java.io.File
import java.nio.charset.StandardCharsets

abstract class WtLexerTestCase : LexerTestCase() {
    override fun createLexer(): Lexer = WtLexerAdapter()
    override fun getDirPath(): String = "src/test/testData/simple"

    fun doTest() {
        val name = getTestName(true)
        val file = File(getDirPath(), "$name.wt")
        require(file.exists()) {
            "Input file not found: ${file.absolutePath}"
        }
        val fileText = FileUtil.loadFile(file, StandardCharsets.UTF_8)

        val tokens = LexerTestUtils.tokenize(fileText, WtLexer()).filter { it.type != TokenType.WHITE_SPACE }
        LexerTestUtils.printTokens(tokens)

        val expectedFile = File(getDirPath(), "$name.txt")
        val actual = printTokens(fileText, 0)
        if (!expectedFile.exists()) {
            println("Expected output file not found: ${expectedFile.absolutePath}")
            println("Actual lexer output:\n$actual")
            expectedFile.parentFile?.mkdirs()
            expectedFile.writeText(actual)
            fail("No output text found. File ${expectedFile.absolutePath} created.")
        }

        val expected = expectedFile.readText(StandardCharsets.UTF_8)
        assertEquals("Lexer output mismatch for $name", expected.trimEnd(), actual.trimEnd())
    }

}
