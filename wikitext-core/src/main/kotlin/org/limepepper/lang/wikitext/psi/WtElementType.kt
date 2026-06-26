package org.limepepper.lang.wikitext.psi

import com.intellij.psi.tree.IElementType
import org.limepepper.lang.wikitext.WtLanguage

/**
 * PSI element type for GDB language constructs
 */
class WtElementType(debugName: String) : IElementType(debugName, WtLanguage) {
    override fun toString(): String = "WtElementType.${super.toString()}"
}
