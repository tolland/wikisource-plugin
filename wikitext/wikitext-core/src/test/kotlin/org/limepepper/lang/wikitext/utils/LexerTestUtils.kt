package org.limepepper.lang.wikitext.utils

import com.intellij.lexer.Lexer
import com.intellij.openapi.diagnostic.logger
import com.intellij.psi.TokenType.WHITE_SPACE
import com.intellij.psi.tree.IElementType
import org.limepepper.lang.wikitext.lexer.WtLexer
import kotlin.test.assertEquals

private val LEXER_LOG = logger<LexerTestUtils>()

data class TokenInfo(
    val type: IElementType,
    val text: String,
    val start: Int,
    val end: Int
)

object LexerTestUtils {
    private val DEBUG: Boolean =
        (System.getProperty("LEXER_DEBUG")?.equals("true", ignoreCase = true) == true) ||
                (System.getenv("LEXER_DEBUG")?.equals("true", ignoreCase = true) == true)

    fun tokenize(content: String, lexer: WtLexer = WtLexer()): List<TokenInfo> {
        val tokens = mutableListOf<TokenInfo>()
        lexer.reset(content, 0, content.length, 0)
        var token: IElementType? = lexer.advance()
        while (token != null) {
            val text = content.substring(lexer.tokenStart, lexer.tokenEnd)
            tokens.add(TokenInfo(token, text, lexer.tokenStart, lexer.tokenEnd))
            token = lexer.advance()
        }
        if (DEBUG) printTokens(tokens)
        return tokens
    }

    fun tokenizeWithAdapter(content: String, lexer: Lexer): List<TokenInfo> {
        val tokens = mutableListOf<TokenInfo>()
        lexer.start(content, 0, content.length, 0)
        while (lexer.tokenType != null) {
            val text = content.substring(lexer.tokenStart, lexer.tokenEnd)
            tokens.add(TokenInfo(lexer.tokenType!!, text, lexer.tokenStart, lexer.tokenEnd))
            lexer.advance()
        }
        if (DEBUG) printTokens(tokens)
        return tokens
    }

    fun printTokens(tokens: List<TokenInfo>) {
        println("==== TOKENS (${tokens.size}) ====")
        var nonWhitespaceIndex = 0
        tokens.forEachIndexed { globalIdx, t ->
            val nonWsIdx = if (t.type != WHITE_SPACE) nonWhitespaceIndex++ else -1
            val indexDisplay = if (nonWsIdx >= 0) "[%3d/%3d]" else "[%3d/   ]"
            if (nonWsIdx >= 0) {
                println(
                    "[%3d/%3d] %-24s | '%s' | %d..%d".format(
                        globalIdx,
                        nonWsIdx,
                        t.type.toString(),
                        escape(t.text),
                        t.start,
                        t.end
                    )
                )
            } else {
                println(
                    "[%3d/   ] %-24s | '%s' | %d..%d".format(
                        globalIdx,
                        t.type.toString(),
                        escape(t.text),
                        t.start,
                        t.end
                    )
                )
            }
        }
    }

    private fun escape(s: String): String = buildString {
        s.forEach { ch ->
            when (ch) {
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> append(ch)
            }
        }
    }

    fun types(tokens: List<TokenInfo>) = tokens.map { it.type }

    fun assertTypes(tokens: List<TokenInfo>, vararg expected: IElementType) {
        assertEquals(expected.toList(), types(tokens))
    }

    fun assertTypesAndTextsExact(tokens: List<TokenInfo>, expected: List<Pair<IElementType, String>>) {
        assertEquals(expected.size, tokens.size, "Token count mismatch")
        expected.forEachIndexed { i, (type, text) ->
            assertEquals(type, tokens[i].type, "Token type mismatch at $i")
            assertEquals(text, tokens[i].text, "Token text mismatch at $i")
        }
    }
}
