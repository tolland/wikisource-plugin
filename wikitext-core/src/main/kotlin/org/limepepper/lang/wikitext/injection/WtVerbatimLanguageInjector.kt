package org.limepepper.lang.wikitext.injection

import com.intellij.lang.Language
import com.intellij.lang.injection.MultiHostInjector
import com.intellij.lang.injection.MultiHostRegistrar
import com.intellij.openapi.util.TextRange
import com.intellij.psi.PsiElement
import org.limepepper.lang.wikitext.psi.WtVerbatimBody
import org.limepepper.lang.wikitext.psi.WtVerbatimContent
import org.limepepper.lang.wikitext.psi.WtVerbatimTag

class WtVerbatimLanguageInjector : MultiHostInjector {

    override fun elementsToInjectIn():
        List<Class<out PsiElement>> =
        listOf(WtVerbatimBody::class.java)

    override fun getLanguagesToInject(
        registrar: MultiHostRegistrar,
        context: PsiElement,
    ) {
        val content = context as? WtVerbatimBody ?: return
        val tag = content.parent as? WtVerbatimTag ?: return

        if (!tag.tagName.equals("math", ignoreCase = true)) {
            println("tag name not math it was ${tag.tagName}")
            return
        }

        val language =
            Language.findLanguageByID("Latex")
                ?: run {
                    println("Language 'Latex' not found for injection")
                    return
                }

        registrar.startInjecting(language)
        registrar.addPlace(
            "\\[", // injected prefix: \[
            "\\]", // injected suffix: \]
            content,
            TextRange(0, content.textLength),
        )
        registrar.doneInjecting()
    }
}
