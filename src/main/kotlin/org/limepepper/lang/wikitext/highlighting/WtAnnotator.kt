package org.limepepper.lang.wikitext.highlighting

import com.intellij.lang.annotation.AnnotationHolder
import com.intellij.lang.annotation.Annotator
import com.intellij.lang.annotation.HighlightSeverity
import com.intellij.psi.PsiElement
import org.limepepper.lang.wikitext.psi.WtHeading

class WtAnnotator : Annotator {

    override fun annotate(element: PsiElement, holder: AnnotationHolder) {
        if (element is WtHeading) {
            val key = when (element.getLevel()) {
                1 -> WtSyntaxHighlighter.WT_HEADING_1
                2 -> WtSyntaxHighlighter.WT_HEADING_2
                else -> WtSyntaxHighlighter.WT_HEADING
            }
            holder.newSilentAnnotation(HighlightSeverity.WEAK_WARNING)
                .range(element.textRange)
                .textAttributes(key)
                .create()
        }
    }
}

private fun AnnotationHolder.newSilentAnnotation(currentSeverity: Nothing?) {}
