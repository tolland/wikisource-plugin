package org.limepepper.lang.wikitext.annotator

import com.intellij.lang.annotation.AnnotationHolder
import com.intellij.lang.annotation.Annotator
import com.intellij.lang.annotation.HighlightSeverity
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.progress.ProgressManager
import com.intellij.openapi.util.TextRange
import com.intellij.psi.PsiElement
import com.intellij.psi.TokenType
import com.intellij.psi.tree.TokenSet
import org.limepepper.lang.wikitext.highlighting.alternateSentenceAttributes
import org.limepepper.lang.wikitext.psi.WtTypes
import org.limepepper.lang.wikitext.psi.WtFile
import java.text.BreakIterator
import java.util.Locale

class WtSentenceBandAnnotator : Annotator, DumbAware {
    override fun annotate(element: PsiElement, holder: AnnotationHolder) {
        if (element !is WtFile) return

        fileSentenceBandRanges(element).forEachIndexed { bandIndex, range ->
            holder.newSilentAnnotation(HighlightSeverity.INFORMATION)
                .range(range)
                .enforcedTextAttributes(alternateSentenceAttributes(bandIndex))
                .create()
        }
    }
}

private val proseTokens = TokenSet.create(
    WtTypes.PLAIN_TEXT, WtTypes.SINGLE_APOS, WtTypes.TWO_APOS,
    WtTypes.THREE_APOS, WtTypes.FIVE_APOS, WtTypes.NEWLINE, TokenType.WHITE_SPACE,
)
private val blankLine = Regex("(?:\\r\\n|[\\r\\n])[^\\S\\r\\n]*(?:\\r\\n|[\\r\\n])")

/** All traversal state belongs to this file-level annotation call. */
internal fun fileSentenceBandRanges(file: WtFile): List<TextRange> {
    val text = file.text
    val bands = mutableListOf<TextRange>()

    fun addRun(start: Int, end: Int) {
        val run = text.substring(start, end)
        var paragraphStart = 0
        fun addParagraph(paragraphEnd: Int) {
            bands.addAll(sentenceBandRanges(run.substring(paragraphStart, paragraphEnd))
                .map { it.shiftRight(start + paragraphStart) })
        }
        blankLine.findAll(run).forEach { separator ->
            addParagraph(separator.range.first)
            paragraphStart = separator.range.last + 1
        }
        addParagraph(run.length)
    }

    fun visitChildren(parent: PsiElement) {
        var runStart: Int? = null
        var runEnd = 0
        fun flush() {
            runStart?.let { addRun(it, runEnd) }
            runStart = null
        }
        var child = parent.firstChild
        while (child != null) {
            ProgressManager.checkCanceled()
            if (child.firstChild == null && child.node.elementType in proseTokens) {
                if (runStart == null) runStart = child.textRange.startOffset
                runEnd = child.textRange.endOffset
            } else {
                flush()
                // Preserve prose inside structural elements, without joining across them.
                if (child.firstChild != null) visitChildren(child)
            }
            child = child.nextSibling
        }
        flush()
    }

    visitChildren(file)
    return bands
}

/** Sentence and clause bands, relative to the supplied prose run. */
internal fun sentenceBandRanges(text: String): List<TextRange> {
    val ranges = mutableListOf<TextRange>()
    val sentences = BreakIterator.getSentenceInstance(Locale.ENGLISH)
    sentences.setText(text)

    fun addBand(start: Int, end: Int) {
        var visibleStart = start
        var visibleEnd = end
        while (visibleStart < visibleEnd && text[visibleStart].isWhitespace()) visibleStart++
        while (visibleEnd > visibleStart && text[visibleEnd - 1].isWhitespace()) visibleEnd--
        if (visibleEnd > visibleStart) ranges.add(TextRange(visibleStart, visibleEnd))
    }

    var sentenceStart = sentences.first()
    var sentenceEnd = sentences.next()
    while (sentenceEnd != BreakIterator.DONE) {
        var bandStart = sentenceStart
        for (index in sentenceStart until sentenceEnd) {
            // Preserve numeric separators such as 1,000 and 3,14.
            val numericComma = text[index] == ',' &&
                text.getOrNull(index - 1)?.isDigit() == true &&
                text.getOrNull(index + 1)?.isDigit() == true
            if (text[index] == ';' || (text[index] == ',' && !numericComma)) {
                addBand(bandStart, index + 1)
                bandStart = index + 1
            }
        }
        addBand(bandStart, sentenceEnd)
        sentenceStart = sentenceEnd
        sentenceEnd = sentences.next()
    }
    return ranges
}
