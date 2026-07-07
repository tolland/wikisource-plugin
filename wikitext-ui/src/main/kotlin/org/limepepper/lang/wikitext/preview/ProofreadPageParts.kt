package org.limepepper.lang.wikitext.preview

/**
 * The three logical sections of a `proofread-page` body, mirroring the split
 * MediaWiki's ProofreadPage extension edit form exposes as `wpHeaderTextbox`,
 * `wpTextbox1`, and `wpFooterTextbox`.
 *
 * On the wire the page is a single serialized string in the shape
 * `<noinclude>header</noinclude>body<noinclude>footer</noinclude>` (the header
 * usually carries the `<pagequality …/>` tag). [decompose] splits that string;
 * [compose] reassembles it. The pair is a Kotlin port of pywikibot's
 * `ProofreadPage._decompose_page` / `_compose_page`, restricted to the modern
 * "V2" (no wrapping `<div class="pagetext">`) layout — see [decompose].
 */
data class ProofreadPageParts(
    val header: String,
    val body: String,
    val footer: String,
) {
    /** Reassemble the serialized page body from its three sections. */
    fun compose(): String =
        OPEN_TAG + header + CLOSE_TAG + body + OPEN_TAG + footer + CLOSE_TAG

    companion object {
        const val OPEN_TAG = "<noinclude>"
        const val CLOSE_TAG = "</noinclude>"

        private val P_OPEN = Regex(Regex.escape(OPEN_TAG))

        // pywikibot's `p_close`: an optional `</div>` (V1 layout) or blank-line
        // separator may precede the closing tag. We only use it to sniff the
        // layout version; the actual split runs on `p_close_no_div`.
        private val P_CLOSE_DIV_AWARE = Regex("(?:</div>|\\n\\n\\n)?</noinclude>")
        private val P_CLOSE = Regex(Regex.escape(CLOSE_TAG))

        /**
         * Split a serialized proofread-page body into header/body/footer, or
         * return `null` when the text is not in a shape we can round-trip
         * losslessly — empty pages, a malformed (unbalanced) tag structure, or
         * the legacy "V1" layout whose `<div class="pagetext">` wrapper the
         * greedy close pattern would swallow. Callers fall back to editing the
         * raw serialized text in those cases rather than risk corrupting it.
         */
        fun decompose(text: String): ProofreadPageParts? {
            if (text.isEmpty()) return null

            val opens = P_OPEN.findAll(text).toList()
            if (opens.size < 2) return null

            // Sniff the layout version off the first section: if the greedy
            // close leaves an opening `<div` in the header, this is the V1
            // format and the closing `</div>` lives outside our three fields.
            val divAwareCloses = P_CLOSE_DIV_AWARE.findAll(text).toList()
            if (divAwareCloses.size != opens.size) return null
            val headerProbe = text.substring(
                opens.first().range.last + 1,
                divAwareCloses.first().range.first,
            )
            if (headerProbe.contains("<div")) return null

            val closes = P_CLOSE.findAll(text).toList()
            if (closes.size != opens.size) return null

            val firstClose = closes.first()
            val lastOpen = opens.last()
            val lastClose = closes.last()

            val header = text.substring(opens.first().range.last + 1, firstClose.range.first)
            val body = text.substring(firstClose.range.last + 1, lastOpen.range.first)
            val footer = text.substring(lastOpen.range.last + 1, lastClose.range.first)
            return ProofreadPageParts(header, body, footer)
        }
    }
}
