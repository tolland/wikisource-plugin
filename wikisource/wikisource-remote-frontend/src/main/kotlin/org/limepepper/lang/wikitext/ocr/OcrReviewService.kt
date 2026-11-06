package org.limepepper.lang.wikitext.ocr

import com.intellij.openapi.components.Service
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindowManager

/**
 * The tool-window-backed [OcrReviewController]: keeps the proposals made
 * during this session and notifies the OCR tool window ([OcrToolWindowFactory]),
 * which renders one closeable tab per proposal. The service is the model,
 * the tool window the view — [present] works (queuing the proposal) even
 * before the tool window's content has ever been built.
 */
@Service(Service.Level.PROJECT)
class OcrReviewService(private val project: Project) : OcrReviewController {
    interface Listener {
        fun proposalAdded(proposal: OcrProposal)
    }

    private val proposals = mutableListOf<OcrProposal>()
    private val listeners = mutableListOf<Listener>()

    fun proposals(): List<OcrProposal> = proposals.toList()

    fun addListener(listener: Listener) {
        listeners += listener
    }

    fun removeListener(listener: Listener) {
        listeners -= listener
    }

    override fun present(proposal: OcrProposal) {
        proposals += proposal
        listeners.toList().forEach { it.proposalAdded(proposal) }
        ToolWindowManager.getInstance(project)
            .getToolWindow(OcrToolWindowFactory.TOOL_WINDOW_ID)
            ?.activate(null)
    }
}
