package org.limepepper.lang.wikitext.psi.impl

import com.intellij.extapi.psi.ASTWrapperPsiElement
import com.intellij.lang.ASTNode
import com.intellij.openapi.util.TextRange
import com.intellij.psi.ElementManipulators
import com.intellij.psi.LiteralTextEscaper
import com.intellij.psi.PsiLanguageInjectionHost

abstract class WtVerbatimBodyMixin(
    node: ASTNode,
) : ASTWrapperPsiElement(node), PsiLanguageInjectionHost {

    override fun isValidHost(): Boolean = true

    override fun updateText(text: String): PsiLanguageInjectionHost =
        ElementManipulators.handleContentChange(this, text)

    override fun createLiteralTextEscaper():
        LiteralTextEscaper<out PsiLanguageInjectionHost> =
        VerbatimLiteralTextEscaper(this)

    private class VerbatimLiteralTextEscaper(
        host: WtVerbatimBodyMixin,
    ) : LiteralTextEscaper<WtVerbatimBodyMixin>(host) {

        override fun decode(
            rangeInsideHost: TextRange,
            outChars: StringBuilder,
        ): Boolean {
            outChars.append(
                myHost.text,
                rangeInsideHost.startOffset,
                rangeInsideHost.endOffset,
            )
            return true
        }

        override fun getOffsetInHost(
            offsetInDecoded: Int,
            rangeInsideHost: TextRange,
        ): Int {
            if (offsetInDecoded < 0) return -1

            val offsetInHost =
                rangeInsideHost.startOffset + offsetInDecoded

            return if (offsetInHost <= rangeInsideHost.endOffset) {
                offsetInHost
            } else {
                -1
            }
        }

        override fun isOneLine(): Boolean = false
    }
}
