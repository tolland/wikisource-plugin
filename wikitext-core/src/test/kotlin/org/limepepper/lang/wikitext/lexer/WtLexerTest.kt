package org.limepepper.lang.wikitext.lexer

import org.jetbrains.annotations.NonNls
import org.limepepper.lang.wikitext.utils.WtLexerTestCase

class WtLexerTest : WtLexerTestCase() {

    // math tag tests
    fun testMathTag() = doTest()

    // simple
    fun testHeaderOneWithNewline() = doTest()
    fun testHelloWorld() = doTest()
    fun testNestedTemplates() = doTest()
    fun testSectionSpans() = doTest()

    // wiki headers
    fun testWikiHeaderLeadingChars() = doTest()
    fun testWikiHeaderOneWithNewline() = doTest()
    fun testWikiHeaderTrailingChars() = doTest()
    fun testWikiHeaderWithEmbeddedTag() = doTest()
    fun testHeaderMissingClosingEqualsChars() = doTest()
    fun testWikiHeaderWithShortEarlyChar() = doTest()

    // links
    fun testWikiLinksSimple() = doTest()

    // tables
    fun testWikiTableLeadingChars() = doTest()
    fun testWikiTableSimple() = doTest()
    fun testTableWithMathTag() = doTest()

    // templates
    fun testAuthorTemplate() = doTest()
    fun testProofreadpage_index_template() = doTest()

    // quote markup ('' italic, ''' bold, ''''' both)
    fun testQuoteBasics() = doTest()
    fun testQuoteApostrophes() = doTest()
    fun testQuoteNestingAmbiguity() = doTest()
    fun testQuoteOddRuns() = doTest()

    // tags
    fun testPagelist_tag() = doTest()

    // content model
    fun testProofread_page_1() = doTest()

}
