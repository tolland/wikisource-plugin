package org.limepepper.lang.wikitext.parser

import org.limepepper.lang.wikitext.psi.WtHeading

object WtPsiImplUtil {

    @JvmStatic
    fun getLevel(heading: WtHeading): Int {
        val text = heading.headingLine.text
        return countLeadingEqualsPairs(text)
    }

    @JvmStatic
    fun getHeadingText(heading: WtHeading): String {
        val text = heading.headingLine.text
        return extractHeaderText(text)
    }

    fun countLeadingEqualsPairs(input: String): Int {
        var count = 0
        var i = 0

        while (i + 1 < input.length && input[i] == '=' && input[i + 1] == '=') {
            count++
            i += 2
        }

        return count
    }

    fun extractHeaderText(input: String): String {
        // Remove leading ==
        val withoutLeading = input.dropWhile { it == '=' }.dropWhile { it == ' ' }

        // Remove trailing ==
        return withoutLeading.trimEnd { it == '=' || it == ' ' }.trim()
    }
}