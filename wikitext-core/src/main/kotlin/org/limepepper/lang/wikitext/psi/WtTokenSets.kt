package org.limepepper.lang.wikitext.psi

import com.intellij.psi.TokenType
import com.intellij.psi.tree.IElementType
import com.intellij.psi.tree.TokenSet

object WtTokenSets {

    // common types
    val WHITESPACE: IElementType = TokenType.WHITE_SPACE

    @JvmField
    val whitespaceTokens = TokenSet.create(
        WtTokenSets.WHITESPACE,
        WtTypes.NEWLINE
    )

    @JvmField
    val COMMENTS = TokenSet.create(
        WtTypes.COMMENT
    )


    @JvmField
    val STRINGS = TokenSet.create(
        WtTypes.PLAIN_TEXT,
        WtTypes.VERBATIM_CONTENT,
    )
}
