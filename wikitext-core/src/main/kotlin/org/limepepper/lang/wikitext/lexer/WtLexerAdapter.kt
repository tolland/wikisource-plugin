package org.limepepper.lang.wikitext.lexer

import com.intellij.lexer.FlexAdapter
import com.intellij.lexer.MergingLexerAdapter
import com.intellij.psi.tree.TokenSet
import org.limepepper.lang.wikitext.psi.WtTypes
import com.intellij.lexer.FlexLexer

/**
 * Lexer adapter that merges consecutive
 *
 */
class WtLexerAdapter : MergingLexerAdapter(
    FlexAdapter(WtLexer(null)),
    TokenSet.create(
        WtTypes.PLAIN_TEXT,
        WtTypes.COMMENT_CONTENT
    )
)
