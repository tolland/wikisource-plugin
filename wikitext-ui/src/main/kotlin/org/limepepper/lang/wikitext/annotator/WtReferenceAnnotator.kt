package org.limepepper.lang.wikitext.annotator

import com.intellij.lang.annotation.AnnotationHolder
import com.intellij.lang.annotation.Annotator
import com.intellij.lang.annotation.HighlightSeverity
import com.intellij.openapi.editor.DefaultLanguageHighlighterColors
import com.intellij.openapi.editor.colors.TextAttributesKey
import com.intellij.openapi.project.DumbAware
import com.intellij.psi.PsiElement
import org.limepepper.lang.wikitext.psi.WtReferenceBody
import org.limepepper.lang.wikitext.psi.WtReferenceTag
import org.limepepper.lang.wikitext.highlighting.WtSyntaxHighlighter
import org.limepepper.lang.wikitext.settings.WtHighlightingSettings

/** Reference content uses a theme-aware secondary text colour, independently of sentence bands. */
class WtReferenceAnnotator : Annotator, DumbAware {
    override fun annotate(element: PsiElement, holder: AnnotationHolder) {
        if (element !is WtReferenceBody && element !is WtReferenceTag) return
        if (!WtHighlightingSettings.getInstance().state.referencesEnabled) return
        val ranges = when (element) {
            is WtReferenceTag -> listOfNotNull(
                element.htmlTagOpen, element.htmlTagClose, element.htmlTagSelfclose,
            ).map { it.textRange }
            else -> listOf(element.textRange).filterNot { it.isEmpty }
        }
        val key = if (element is WtReferenceBody) REFERENCE_CONTENT else WtSyntaxHighlighter.MARKUP_TAG
        ranges.forEach { range ->
            holder.newSilentAnnotation(HighlightSeverity.INFORMATION)
                .range(range)
                .textAttributes(key)
                .create()
        }
    }

    companion object {
        val REFERENCE_CONTENT = TextAttributesKey.createTextAttributesKey(
            "WT_REFERENCE_CONTENT", DefaultLanguageHighlighterColors.BLOCK_COMMENT,
        )
    }
}
