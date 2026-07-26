package org.limepepper.lang.wikitext.annotator

import com.intellij.lang.annotation.AnnotationHolder
import com.intellij.lang.annotation.Annotator
import com.intellij.lang.annotation.HighlightSeverity
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.util.TextRange
import com.intellij.psi.PsiElement
import org.limepepper.lang.wikitext.highlighting.alternateSentenceAttributes
import org.limepepper.lang.wikitext.psi.WtTypes
import java.text.BreakIterator
import java.util.*

class WtSentenceBandAnnotator : Annotator, DumbAware {
    override fun annotate(element: PsiElement, holder: AnnotationHolder) {
        if (element.node.elementType != WtTypes.PLAIN_TEXT) return

        val text = element.text
        val baseOffset = element.textRange.startOffset
        val sentences = BreakIterator.getSentenceInstance(Locale.ENGLISH)

        sentences.setText(text)

        var start = sentences.first()
        var end = sentences.next()
        var sentenceIndex = 0

        while (end != BreakIterator.DONE) {
            // Avoid colouring whitespace belonging to the next sentence.
            var visibleEnd = end
            while (visibleEnd > start && text[visibleEnd - 1].isWhitespace()) {
                visibleEnd--
            }

            if (visibleEnd > start) {
                holder.newSilentAnnotation(HighlightSeverity.INFORMATION)
                    .range(
                        TextRange(
                            baseOffset + start,
                            baseOffset + visibleEnd,
                        ),
                    )
                    .enforcedTextAttributes(alternateSentenceAttributes(sentenceIndex))
                    .create()
            }

            sentenceIndex++
            start = end
            end = sentences.next()
        }
    }
}
