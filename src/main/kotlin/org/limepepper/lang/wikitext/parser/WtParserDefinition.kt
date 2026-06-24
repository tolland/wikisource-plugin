package org.limepepper.lang.wikitext.parser

import com.intellij.lang.ASTNode
import com.intellij.lang.ParserDefinition
import com.intellij.lang.PsiParser
import com.intellij.lexer.Lexer
import com.intellij.openapi.project.Project
import com.intellij.psi.FileViewProvider
import com.intellij.psi.PsiElement
import com.intellij.psi.PsiFile
import com.intellij.psi.tree.IFileElementType
import com.intellij.psi.tree.TokenSet
import org.limepepper.lang.wikitext.WtLanguage
import org.limepepper.lang.wikitext.lexer.WtLexerAdapter
import org.limepepper.lang.wikitext.psi.WtTypes
import org.limepepper.lang.wikitext.psi.WtFile

/**
 * Parser definition for Wikitext language
 */
class WtParserDefinition : ParserDefinition {

    companion object {
        val FILE = IFileElementType(WtLanguage)
    }

    override fun createLexer(project: Project?): Lexer = WtLexerAdapter()

    override fun createParser(project: Project?): PsiParser {
        return WtParser() // Generated parser
    }

    override fun getFileNodeType(): IFileElementType = FILE

    override fun getCommentTokens(): TokenSet = WtTokenSets.COMMENTS

    override fun getStringLiteralElements(): TokenSet = WtTokenSets.STRINGS

    override fun getWhitespaceTokens(): TokenSet = WtTokenSets.whitespaceTokens

    override fun createElement(node: ASTNode): PsiElement {
        // Use the generated factory method
        return WtTypes.Factory.createElement(node)
    }

    override fun createFile(viewProvider: FileViewProvider): PsiFile {
        return WtFile(viewProvider)
    }
}
