package org.limepepper.lang.wikitext.lexer

import com.intellij.lexer.Lexer
import com.intellij.psi.TokenType
import com.intellij.testFramework.LexerTestCase
import org.jetbrains.annotations.NonNls
import org.limepepper.lang.wikitext.psi.WtTypes
import org.limepepper.lang.wikitext.utils.LexerTestUtils

class WtLexerTest : LexerTestCase() {
    override fun createLexer(): Lexer = WtLexerAdapter()

    override fun getDirPath(): String = "src/test/testData"

    fun testSimple() = doTest("hello world!")

    fun testSimpleString() {
        val content = """
            hello world!
         """.trimIndent()

        val tokens = LexerTestUtils.tokenize(content, WtLexer()).filter { it.type != TokenType.WHITE_SPACE }
        LexerTestUtils.printTokens(tokens)
    }

    override fun doTest(text: @NonNls String) {
        super.doTest(text)
        checkCorrectRestart(text)
    }

    fun testSomeRandomWikitextToSeeIfitBreaks() {
        val content = """
            {{author
            | firstname    = Julien Offray
            | lastname     = de La Mettrie
            }}
            
            == this is h1 ==    
            
            This is <span style="color:red;">red</span> text.
            
            {{File:somefile.jpg}}
            
            {{ph|class=_test|{{sc|nest this in a another template}}
            }}
            
            <section begin"ch=1" />
            
            <h1>Heading 1</h1>
            one space indented
            
            <ref>this is a ref</ref>
            
            <nowiki>
            
            {{{ this is some nowikie
            
            <html>
            
            </nowiki>
            
            ''this is not missing end quotes''
            
            '''''this is missing end quotes


        """.trimIndent()

        val tokens = LexerTestUtils.tokenize(content, WtLexer()).filter { it.type != TokenType.WHITE_SPACE }
        LexerTestUtils.printTokens(tokens)

        assertTrue(tokens.none { it.type == TokenType.BAD_CHARACTER })
        assertEquals(WtTypes.TEMPLATE_OPEN, tokens[0].type)
        assertEquals(WtTypes.TEMPLATE_NAME, tokens[1].type)
        assertEquals(WtTypes.NEWLINE, tokens.get(tokens.size - 1).type)
    }
}
