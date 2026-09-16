package org.limepepper.lang.wikitext.annotator

import com.intellij.testFramework.ParsingTestCase
import org.limepepper.lang.wikitext.parser.WtParserDefinition
import org.limepepper.lang.wikitext.psi.WtFile

class WtFileSentenceBandTest : ParsingTestCase("", "wt", true, WtParserDefinition()) {
    override fun getTestDataPath(): String = "src/test/resources"

    private fun bands(text: String): List<String> {
        parseFile("bands", text)
        return fileSentenceBandRanges(myFile as WtFile).map {
            assertTrue(it.startOffset >= 0 && it.endOffset <= text.length)
            text.substring(it.startOffset, it.endOffset)
        }
    }

    fun testFormattingDoesNotBreakProse() {
        assertEquals(
            listOf("Don't stop at ''italic'' or '''bold''' or '''''both''''',", "keep going;", "then finish."),
            bands("Don't stop at ''italic'' or '''bold''' or '''''both''''', keep going; then finish."),
        )
    }

    fun testBlankLinesBreakRunsButSingleNewlinesDoNot() {
        assertEquals(
            listOf("First\nwrapped line", "Second paragraph"),
            bands("First\nwrapped line\n \t\nSecond paragraph"),
        )
    }

    fun testStructuralElementsSeparateSurroundingProse() {
        assertEquals(listOf("Before", "After"), bands("Before{{example}}After"))
        assertEquals(listOf("Before", "inside", "After"), bands("Before<u>inside</u>After"))
    }

    fun testSeparateFilesDoNotShareTraversalState() {
        assertEquals(listOf("One,", "two."), bands("One, two."))
        assertEquals(listOf("New ''text''."), bands("New ''text''."))
    }
}
