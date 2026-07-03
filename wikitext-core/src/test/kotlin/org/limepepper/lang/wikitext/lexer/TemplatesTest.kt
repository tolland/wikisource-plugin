package org.limepepper.lang.wikitext.lexer

import com.intellij.psi.TokenType
import org.junit.Test
import org.limepepper.lang.wikitext.psi.WtTypes
import org.limepepper.lang.wikitext.utils.LexerTestUtils
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class TemplatesTest {
    @Test
    fun templateSimple1() {
        val content = """
            {{author
            | firstname    = Julien Offray
            | lastname     = de La Mettrie
            }}

        """.trimIndent()

        val tokens = LexerTestUtils.tokenize(content, WtLexer()).filter { it.type != TokenType.WHITE_SPACE }

        assertTrue(tokens.none { it.type == TokenType.BAD_CHARACTER })
        assertEquals(WtTypes.TEMPLATE_OPEN, tokens[0].type)
        assertEquals(WtTypes.TEMPLATE_NAME, tokens[1].type)
        assertEquals(WtTypes.NEWLINE, tokens.get(tokens.size - 1).type)
    }
    @Test
    fun templateSimple2() {
        // Nest a template in a template
        val content = """
            {{ph|class=_test|{{sc|nest this in a another template}}
            }}

        """.trimIndent()

        val tokens = LexerTestUtils.tokenize(content, WtLexer()).filter { it.type != TokenType.WHITE_SPACE }

        assertTrue(tokens.none { it.type == TokenType.BAD_CHARACTER })
        assertEquals(WtTypes.TEMPLATE_OPEN, tokens[0].type)
        assertEquals(WtTypes.TEMPLATE_NAME, tokens[1].type)
        assertEquals(WtTypes.NEWLINE, tokens.get(tokens.size - 1).type)
    }
}
