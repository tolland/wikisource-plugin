package org.limepepper.lang.wikitext.annotator

import com.intellij.lang.annotation.AnnotationHolder
import com.intellij.lang.annotation.Annotator
import com.intellij.lang.annotation.HighlightSeverity
import com.intellij.openapi.editor.DefaultLanguageHighlighterColors
import com.intellij.openapi.editor.colors.TextAttributesKey
import com.intellij.openapi.project.DumbAware
import com.intellij.psi.PsiElement
import org.limepepper.lang.wikitext.semantics.WtSemanticViews
import org.limepepper.lang.wikitext.highlighting.WtSyntaxHighlighter
import org.limepepper.lang.wikitext.settings.WtHighlightingSettings

/** Reference content uses a theme-aware secondary text colour, independently of sentence bands. */
class WtReferenceAnnotator : Annotator, DumbAware {
    override fun annotate(element: PsiElement, holder: AnnotationHolder) {
        val reference = WtSemanticViews.reference(element) ?: return
        if (!WtHighlightingSettings.getInstance().state.referencesEnabled) return
        val tag = reference.tag
        listOfNotNull(tag.openingRange, tag.closingRange).forEach { range ->
            holder.newSilentAnnotation(HighlightSeverity.INFORMATION)
                .range(range)
                .textAttributes(WtSyntaxHighlighter.MARKUP_TAG)
                .create()
        }
        reference.bodyRange?.takeUnless { it.isEmpty }?.let { range ->
            holder.newSilentAnnotation(HighlightSeverity.INFORMATION)
                .range(range)
                .textAttributes(REFERENCE_CONTENT)
                .create()
        }
    }

    companion object {
        val REFERENCE_CONTENT = TextAttributesKey.createTextAttributesKey(
            "WT_REFERENCE_CONTENT", DefaultLanguageHighlighterColors.BLOCK_COMMENT,
        )
    }
}
