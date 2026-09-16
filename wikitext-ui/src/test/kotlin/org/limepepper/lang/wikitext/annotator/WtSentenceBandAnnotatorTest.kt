package org.limepepper.lang.wikitext.annotator

import com.intellij.openapi.util.TextRange
import kotlin.test.Test
import kotlin.test.assertEquals

class WtSentenceBandAnnotatorTest {
    @Test
    fun `splits clauses and sentences keeping punctuation with the preceding text`() {
        val text = "First clause, second clause; final clause. Next sentence!"
        assertEquals(
            listOf("First clause,", "second clause;", "final clause.", "Next sentence!"),
            sentenceBandRanges(text).map { text.substring(it.startOffset, it.endOffset) },
        )
    }

    @Test
    fun `preserves numeric commas but splits commas without spaces`() {
        val text = "Values 1,000 and 3,14,then more;finally."
        assertEquals(
            listOf("Values 1,000 and 3,14,", "then more;", "finally."),
            sentenceBandRanges(text).map { text.substring(it.startOffset, it.endOffset) },
        )
    }

    @Test
    fun `excludes surrounding whitespace and retains exact offsets`() {
        assertEquals(
            listOf(TextRange(2, 6), TextRange(9, 13), TextRange(15, 20)),
            sentenceBandRanges("  One, \n two;\t three  "),
        )
    }

    @Test
    fun `ignores empty bands after trailing punctuation and whitespace`() {
        assertEquals(emptyList(), sentenceBandRanges(""))
        assertEquals(emptyList(), sentenceBandRanges(" \n\t"))
        assertEquals(listOf(TextRange(0, 5)), sentenceBandRanges("Only;  "))
    }
}
