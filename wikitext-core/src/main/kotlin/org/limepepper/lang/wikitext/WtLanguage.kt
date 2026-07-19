package org.limepepper.lang.wikitext

import com.intellij.lang.Language

object WtLanguage : Language(
    "Wikitext",
    "text/x-wiki"
) {
    override fun isCaseSensitive() = true

}
