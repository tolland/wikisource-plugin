package org.limepepper.lang.wikitext.preview

/**
 * The `<pagequality level="…" user="…" />` tag that leads a proofread-page
 * header, carrying the ProofreadPage extension's quality level and the user
 * who set it. Levels mirror pywikibot's `ProofreadPage.PROOFREAD_LEVELS`.
 */
data class PageQuality(val level: Int, val user: String) {
    fun compose(): String = """<pagequality level="$level" user="$user" />"""

    companion object {
        const val WITHOUT_TEXT = 0
        const val NOT_PROOFREAD = 1
        const val PROBLEMATIC = 2
        const val PROOFREAD = 3
        const val VALIDATED = 4

        val LEVELS: IntRange = WITHOUT_TEXT..VALIDATED

        fun levelName(level: Int): String = when (level) {
            WITHOUT_TEXT -> "Without text"
            NOT_PROOFREAD -> "Not proofread"
            PROBLEMATIC -> "Problematic"
            PROOFREAD -> "Proofread"
            VALIDATED -> "Validated"
            else -> "Level $level"
        }
    }
}

/**
 * The first `<noinclude>` section of a proofread-page: an optional leading
 * [PageQuality] tag plus the user-editable header wikitext (running headers
 * like `{{rh|…}}` and the like). Port of pywikibot's `FullHeader`, with one
 * deliberate difference: pywikibot's `re.search` accepts the tag anywhere and
 * silently drops whatever precedes it on recompose, while [parse] only
 * recognizes the tag at the very start of the section — anything else stays
 * verbatim in [text], so `parse` → [compose] is always lossless.
 */
data class ProofreadPageHeader(
    val quality: PageQuality?,
    val text: String,
) {
    fun compose(): String = (quality?.compose() ?: "") + text

    companion object {
        // pywikibot FullHeader.p_header, minus the V1 `<div class="pagetext">`
        // group (V1 pages are rejected before this parse ever runs) and
        // anchored at the section start (see the class doc).
        private val P_QUALITY = Regex("""^<pagequality level="(\d)" user="(.*?)" />""")

        fun parse(headerText: String): ProofreadPageHeader {
            val match = P_QUALITY.find(headerText)
                ?: return ProofreadPageHeader(quality = null, text = headerText)
            return ProofreadPageHeader(
                quality = PageQuality(
                    level = match.groupValues[1].toInt(),
                    user = match.groupValues[2],
                ),
                text = headerText.substring(match.range.last + 1),
            )
        }
    }
}

/**
 * The three logical sections of a `proofread-page` body, mirroring the split
 * MediaWiki's ProofreadPage extension edit form exposes as `wpHeaderTextbox`,
 * `wpTextbox1`, and `wpFooterTextbox` (plus the page-quality radio group,
 * modeled by [ProofreadPageHeader.quality]).
 *
 * On the wire the page is a single serialized string in the shape
 * `<noinclude><pagequality …/>header</noinclude>body<noinclude>footer</noinclude>`.
 * [decompose] splits that string; [compose] reassembles it. The pair is a
 * Kotlin port of pywikibot's `ProofreadPage._decompose_page` /
 * `_compose_page`, restricted to the modern "V2" (no wrapping
 * `<div class="pagetext">`) layout — see [decompose].
 */
data class ProofreadPageParts(
    val header: ProofreadPageHeader,
    val body: String,
    val footer: String,
) {
    /** Reassemble the serialized page body from its three sections. */
    fun compose(): String =
        OPEN_TAG + header.compose() + CLOSE_TAG + body + OPEN_TAG + footer + CLOSE_TAG

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
         * Skeleton for a page generated on the fly — the analogue of
         * pywikibot's `_create_empty_page`, which stamps a fresh page with a
         * not-proofread [PageQuality] for the current user and empty sections.
         */
        fun newPage(user: String, level: Int = PageQuality.NOT_PROOFREAD): ProofreadPageParts =
            ProofreadPageParts(
                header = ProofreadPageHeader(PageQuality(level, user), ""),
                body = "",
                footer = "",
            )

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
            return ProofreadPageParts(ProofreadPageHeader.parse(header), body, footer)
        }
    }
}
