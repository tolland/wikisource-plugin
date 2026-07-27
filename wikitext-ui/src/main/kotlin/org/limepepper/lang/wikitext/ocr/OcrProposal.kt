package org.limepepper.lang.wikitext.ocr

/**
 * One OCR response awaiting human review — the stable value object between
 * whoever produced the text (the bounding-box menu today; batch OCR
 * pipelines later) and whatever surface presents it for a decision (the
 * OCR tool window today; an inline diff, intention-action preview, or
 * accept/reject chrome later). Producers and presenters both depend only
 * on this class and [OcrReviewController], so the presentation can be
 * swapped without touching the producers.
 *
 * [applyToTarget] is the single write path: the producer captures where
 * the text belongs (today: the box's linked text range) and the presenter
 * invokes it with the possibly user-edited text when the user accepts.
 * Null means the proposal is display/copy only. It returns a user-facing
 * error message, or null on success — the presenter decides how to show
 * either outcome. Must be invoked on the EDT.
 */
class OcrProposal(
    /** Short label for tabs/headers, e.g. the page name + box label. */
    val title: String,
    val pagePath: String? = null,
    val boxId: String? = null,
    /** Backend name and engine that produced [text], for provenance. */
    val backend: String,
    val engine: String? = null,
    val text: String,
    val applyToTarget: ((String) -> String?)? = null,
)
