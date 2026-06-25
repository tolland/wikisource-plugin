package org.limepepper.lang.wikitext.highlighting

import com.intellij.lexer.Lexer
import com.intellij.openapi.editor.DefaultLanguageHighlighterColors
import com.intellij.openapi.editor.HighlighterColors
import com.intellij.openapi.editor.colors.TextAttributesKey
import com.intellij.openapi.fileTypes.SyntaxHighlighterBase
import com.intellij.psi.tree.IElementType
import org.limepepper.lang.wikitext.lexer.WtLexerAdapter
import org.limepepper.lang.wikitext.psi.WtTokenSets
import org.limepepper.lang.wikitext.psi.WtTypes

class WtSyntaxHighlighter : SyntaxHighlighterBase() {

    companion object {
        // Define text attribute keys for different syntax elements
        @JvmField
        val COMMENT = TextAttributesKey.createTextAttributesKey(
            "WT_COMMENT",
            DefaultLanguageHighlighterColors.LINE_COMMENT
        )

        @JvmField val IDENTIFIER = TextAttributesKey.createTextAttributesKey(
            "WT_IDENTIFIER",
            DefaultLanguageHighlighterColors.STRING
        )

        val TEMPLATE_TRANSCLUSION = TextAttributesKey.createTextAttributesKey(
            "WT_TEMPLATE_TRANSCLUSION",
            DefaultLanguageHighlighterColors.FUNCTION_CALL
        )

        @JvmField
        val TEXT = TextAttributesKey.createTextAttributesKey(
            "WT_TEXT",
            DefaultLanguageHighlighterColors.STRING
        )


        @JvmField
        val BAD_CHARACTER = TextAttributesKey.createTextAttributesKey(
            "GDB_BAD_CHARACTER",
            HighlighterColors.BAD_CHARACTER
        )

        val WT_TEMPLATE_NAME = TextAttributesKey.createTextAttributesKey(
            "WT_TEMPLATE_NAME",
            DefaultLanguageHighlighterColors.FUNCTION_CALL
        )
        val WT_BODY_TEXT = TextAttributesKey.createTextAttributesKey(
            "WT_BODY_TEXT",
            HighlighterColors.TEXT  // i.e. plain, no extra styling
        )
        val WT_HEADING = TextAttributesKey.createTextAttributesKey(
            "WT_HEADING",
            DefaultLanguageHighlighterColors.STATIC_METHOD
        )
        val WT_HEADING_1 = TextAttributesKey.createTextAttributesKey(
            "WT_HEADING_1",
            DefaultLanguageHighlighterColors.INVALID_STRING_ESCAPE
        )
        val WT_HEADING_2 = TextAttributesKey.createTextAttributesKey(
            "WT_HEADING_2",
            DefaultLanguageHighlighterColors.KEYWORD
        )
        val MARKUP_TAG = TextAttributesKey.createTextAttributesKey(
            "MARKUP_TAG",
            DefaultLanguageHighlighterColors.MARKUP_TAG
        )
        val WT_KEYWORD = TextAttributesKey.createTextAttributesKey(
            "WT_KEYWORD",
            DefaultLanguageHighlighterColors.KEYWORD
        )
        val WT_INTERNAL_LINK_TARGET = TextAttributesKey.createTextAttributesKey(
            "WT_INTERNAL_LINK_TARGET",
            DefaultLanguageHighlighterColors.HIGHLIGHTED_REFERENCE
        )
        val TEMPLATE_LANGUAGE_COLOR = TextAttributesKey.createTextAttributesKey(
            "WT_TEMPLATE_LANGUAGE",
            DefaultLanguageHighlighterColors.TEMPLATE_LANGUAGE_COLOR
        )


    }

    override fun getHighlightingLexer(): Lexer = WtLexerAdapter()

    override fun getTokenHighlights(tokenType: IElementType): Array<TextAttributesKey> {
        return when {
            // Use TokenSets for cleaner code - reference the correct attributes
            tokenType in WtTokenSets.COMMENTS -> arrayOf(COMMENT)
            tokenType in WtTokenSets.STRINGS -> arrayOf(WT_BODY_TEXT)

            // Specific token highlighting
            tokenType == WtTypes.TEMPLATE -> arrayOf(TEMPLATE_TRANSCLUSION)
            tokenType == WtTypes.TEMPLATE_NAME -> arrayOf(IDENTIFIER)
            tokenType == WtTypes.TEMPLATE_NAME -> arrayOf(TEMPLATE_LANGUAGE_COLOR)
            tokenType == WtTypes.INTERNAL_LINK -> arrayOf(TEMPLATE_LANGUAGE_COLOR)
            tokenType == WtTypes.LINK_TARGET -> arrayOf(IDENTIFIER)
            tokenType == WtTypes.HTML_TAG_SELFCLOSE -> arrayOf(IDENTIFIER)
//            tokenType == WtTypes.HEADING -> arrayOf(IDENTIFIER)
//            tokenType == WtTypes.HEADING_LINE -> arrayOf(WT_KEYWORD)
            tokenType == WtTypes.TEMPLATE_PARAM_TEXT -> arrayOf(WT_KEYWORD)
            else -> emptyArray()
        }
    }
}