package org.limepepper.lang.wikitext.annotator

import com.intellij.lang.annotation.AnnotationHolder
import com.intellij.lang.annotation.Annotator
import com.intellij.lang.annotation.HighlightSeverity
import com.intellij.openapi.editor.colors.EditorColorsManager
import com.intellij.openapi.project.DumbAware
import com.intellij.psi.PsiElement
import org.limepepper.lang.wikitext.highlighting.SentenceBandHighlightingStrategy
import org.limepepper.lang.wikitext.psi.WtFile
import org.limepepper.lang.wikitext.settings.WtHighlightingSettings

/** Connects prose boundaries to presentation; neither policy depends on the other. */
class WtSentenceBandAnnotator(
    private val highlighting: SentenceBandHighlightingStrategy? = null,
) : Annotator, DumbAware {
    override fun annotate(element: PsiElement, holder: AnnotationHolder) {
        if (element !is WtFile) return

        val strategy = highlighting ?: WtHighlightingSettings.getInstance().bandHighlighting() ?: return
        val scheme = EditorColorsManager.getInstance().globalScheme
        fileSentenceBandRanges(element).forEachIndexed { bandIndex, range ->
            val attributes = strategy.attributes(bandIndex, scheme) ?: return@forEachIndexed
            holder.newSilentAnnotation(HighlightSeverity.INFORMATION)
                .range(range)
                .enforcedTextAttributes(attributes)
                .create()
        }
    }
}
