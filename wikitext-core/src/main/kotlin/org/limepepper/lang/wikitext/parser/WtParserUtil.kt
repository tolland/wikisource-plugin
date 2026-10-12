package org.limepepper.lang.wikitext.parser

import com.intellij.lang.PsiBuilder
import com.intellij.lang.parser.GeneratedParserUtilBase
import org.limepepper.lang.wikitext.psi.WtTypes

object WtParserUtil : GeneratedParserUtilBase() {
    /** Look ahead only: generic tags and verbatim content keep their existing grammar. */
    @JvmStatic
    fun isReferenceTag(builder: PsiBuilder, level: Int): Boolean {
        if (builder.tokenType != WtTypes.HTML_TAG_OPEN &&
            builder.tokenType != WtTypes.HTML_TAG_SELFCLOSE
        ) return false
        val name = builder.tokenText?.drop(1)?.takeWhile { it.isLetterOrDigit() }
        return name.equals("ref", ignoreCase = true)
    }
}
