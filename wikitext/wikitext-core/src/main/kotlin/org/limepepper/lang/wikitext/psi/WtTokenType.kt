package org.limepepper.lang.wikitext.psi

import com.intellij.psi.tree.IElementType
import org.limepepper.lang.wikitext.WtLanguage

class WtTokenType (debugName: String) : IElementType(debugName, WtLanguage) {
    override fun toString(): String = "WtTokenType.${super.toString()}"
}
