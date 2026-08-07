package org.limepepper.lang.wikitext.editing

/**
 * The result of wrapping a piece of text in a [WtWrapTag]: the replacement
 * text plus the offsets a caller needs to drive the editor afterwards. All
 * offsets are relative to [text], so the caller only has to add the document
 * offset the replacement was inserted at.
 */
data class WtWrapRendering(
    /** The full replacement for the original selection. */
    val text: String,
    /** Where the original selection ended up inside [text]. */
    val contentStart: Int,
    val contentEnd: Int,
    /**
     * Every occurrence of the tag's variable placeholder, in document order.
     * Empty for constructs with no variable. Occurrences are *mirrors* of one
     * value (see [WtWrapTag.SECTION]) — a caller filling them in must write
     * the same text to all of them.
     */
    val variableRanges: List<IntRange>,
) {
    val hasVariables: Boolean get() = variableRanges.isNotEmpty()
}

/**
 * Turns a selection plus a [WtWrapTag] into the text that replaces it.
 *
 * Pure and IDE-free on purpose: this is the part worth unit-testing
 * exhaustively, and keeping it out of the surrounders means the several
 * competing surround implementations (document-edit, live-template, …) all
 * produce byte-identical markup and differ only in how they *interact*.
 */
object WtWrapRenderer {

    /**
     * Wraps [selection] in [tag].
     *
     * [variableValue] fills the tag's placeholder. Passing null substitutes
     * [DEFAULT_PLACEHOLDER], which is what a plain-text caller wants — it then
     * selects [WtWrapRendering.variableRanges] so the user types over it. A
     * live-template-driven caller passes [WtWrapTag.VARIABLE] back in, leaving
     * the placeholder as template syntax for the template engine to mirror.
     *
     * [indent] is the leading whitespace of the line the selection starts on;
     * block-level tags reuse it for their marker lines so a wrapped block does
     * not lose the surrounding indentation. Pass "" when it does not matter.
     */
    fun render(
        tag: WtWrapTag,
        selection: String,
        variableValue: String? = null,
        indent: String = "",
    ): WtWrapRendering {
        val placeholder = if (tag.hasVariable) (variableValue ?: DEFAULT_PLACEHOLDER) else null
        val prefix = tag.prefix.substituteVariable(placeholder)
        val suffix = tag.suffix.substituteVariable(placeholder)

        val builder = StringBuilder()
        builder.append(prefix)
        if (tag.block) {
            builder.append('\n').append(indent)
        }
        val contentStart = builder.length
        builder.append(selection)
        val contentEnd = builder.length
        if (tag.block) {
            builder.append('\n').append(indent)
        }
        builder.append(suffix)

        val text = builder.toString()
        val variableRanges = if (placeholder == null) {
            emptyList()
        } else {
            text.occurrencesOf(placeholder)
        }
        return WtWrapRendering(text, contentStart, contentEnd, variableRanges)
    }

    /**
     * The leading whitespace of the line containing [offset] in [document
     * text][text]. Exposed because every surround implementation needs it and
     * none of them should be re-deriving it.
     */
    fun indentOfLineAt(text: CharSequence, offset: Int): String {
        var lineStart = offset.coerceIn(0, text.length)
        while (lineStart > 0 && text[lineStart - 1] != '\n') lineStart--
        var end = lineStart
        while (end < text.length && (text[end] == ' ' || text[end] == '\t')) end++
        return text.subSequence(lineStart, end).toString()
    }

    private fun String.substituteVariable(value: String?): String =
        if (value == null) this else replace(WtWrapTag.VARIABLE, value)

    /**
     * All occurrences of [needle], which for the mirrored-variable case is how
     * the begin and end markers are found without re-parsing the markup.
     */
    private fun String.occurrencesOf(needle: String): List<IntRange> {
        if (needle.isEmpty()) return emptyList()
        val found = mutableListOf<IntRange>()
        var from = indexOf(needle)
        while (from >= 0) {
            found += from until (from + needle.length)
            from = indexOf(needle, from + needle.length)
        }
        return found
    }

    /**
     * Stand-in written into the document when no value was supplied — the user
     * types over it. Not [WtWrapTag.VARIABLE] itself: `$NAME$` would leave
     * live-template syntax sitting in saved wikitext if the user walked away
     * mid-edit, whereas this reads as an obvious placeholder on the wiki.
     */
    const val DEFAULT_PLACEHOLDER: String = "name"
}
