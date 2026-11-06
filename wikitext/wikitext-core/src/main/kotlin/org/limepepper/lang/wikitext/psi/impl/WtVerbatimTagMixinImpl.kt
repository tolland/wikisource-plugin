package org.limepepper.lang.wikitext.psi.impl

import com.intellij.extapi.psi.ASTWrapperPsiElement
import com.intellij.lang.ASTNode
import org.limepepper.lang.wikitext.psi.WtVerbatimTagMixin
import org.limepepper.lang.wikitext.psi.WtTypes

abstract class WtVerbatimTagMixinImpl(
    node: ASTNode,
) : ASTWrapperPsiElement(node), WtVerbatimTagMixin {

    override val tagName: String?
        get() {
            val opening = node
                .findChildByType(WtTypes.HTML_TAG_OPEN)
                ?.text
                ?: return null

            return opening
                .removePrefix("<")
                .trimStart()
                .takeWhile { character ->
                    character.isLetterOrDigit() ||
                        character == '-' ||
                        character == ':'
                }
                .takeIf { it.isNotEmpty() }
        }
}
