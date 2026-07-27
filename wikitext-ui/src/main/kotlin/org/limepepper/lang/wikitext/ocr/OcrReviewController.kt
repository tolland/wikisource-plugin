package org.limepepper.lang.wikitext.ocr

import com.intellij.openapi.components.service
import com.intellij.openapi.project.Project

/**
 * The boundary producers of OCR text call to get a result reviewed. The
 * current implementation ([OcrReviewService]) presents proposals in the
 * OCR tool window; the review UX is expected to evolve (inline diffs,
 * intention-preview-style accept/reject, …), and only implementations of
 * this interface change when it does — producers keep calling [present]
 * with an [OcrProposal].
 */
interface OcrReviewController {
    /** Presents [proposal] for review. Call on the EDT. */
    fun present(proposal: OcrProposal)

    companion object {
        fun getInstance(project: Project): OcrReviewController =
            project.service<OcrReviewService>()
    }
}
