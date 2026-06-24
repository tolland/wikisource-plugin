package org.limepepper.lang.wikitext.parser

import com.intellij.psi.TokenType
import com.intellij.psi.tree.IElementType
import com.intellij.psi.tree.TokenSet
import org.limepepper.lang.wikitext.psi.WtTypes

object WtTokenSets {

    // common types
    val WHITESPACE: IElementType = TokenType.WHITE_SPACE

    @JvmField
    val whitespaceTokens = TokenSet.create(
        org.limepepper.lang.wikitext.parser.WtTokenSets.WHITESPACE,
        WtTypes.NEWLINE
    )


    // @TODO wikitext has comments we should parse them
    @JvmField
    val COMMENTS = TokenSet.create()


    @JvmField
    val STRINGS = TokenSet.create(
        WtTypes.PLAIN_TEXT,
        WtTypes.VERBATIM_CONTENT,
    )
}