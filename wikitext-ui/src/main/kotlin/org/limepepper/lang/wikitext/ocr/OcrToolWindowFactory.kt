package org.limepepper.lang.wikitext.ocr

import com.intellij.openapi.components.service
import com.intellij.openapi.ide.CopyPasteManager
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import com.intellij.util.ui.JBUI
import java.awt.BorderLayout
import java.awt.FlowLayout
import java.awt.datatransfer.StringSelection
import javax.swing.JButton
import javax.swing.JPanel

/**
 * The OCR tool window: one closeable tab per [OcrProposal] presented via
 * [OcrReviewService]. Deliberately minimal — an editable text area (fix the
 * recognition before applying), an apply button routed through the
 * proposal's [OcrProposal.applyToTarget], and copy — because the review
 * UX is expected to be replaced; the boundaries that stay are
 * [OcrReviewController] and [OcrProposal], not this panel.
 */
class OcrToolWindowFactory : ToolWindowFactory, DumbAware {
    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val service = project.service<OcrReviewService>()
        val listener = object : OcrReviewService.Listener {
            override fun proposalAdded(proposal: OcrProposal) =
                addTab(toolWindow, proposal)
        }
        service.addListener(listener)
        toolWindow.disposable.let { parent ->
            com.intellij.openapi.util.Disposer.register(parent) {
                service.removeListener(listener)
            }
        }
        // Proposals presented before the tool window was first opened.
        service.proposals().forEach { addTab(toolWindow, it) }
    }

    private fun addTab(toolWindow: ToolWindow, proposal: OcrProposal) {
        val content = toolWindow.contentManager.factory.createContent(
            OcrProposalPanel(proposal),
            proposal.title,
            false,
        )
        content.isCloseable = true
        toolWindow.contentManager.addContent(content)
        toolWindow.contentManager.setSelectedContent(content)
    }

    companion object {
        const val TOOL_WINDOW_ID = "Wikisource OCR"
    }
}

/** One proposal's review surface: provenance header, editable text, actions. */
private class OcrProposalPanel(private val proposal: OcrProposal) : JPanel(BorderLayout()) {
    private val textArea = JBTextArea(proposal.text).apply {
        lineWrap = true
        wrapStyleWord = true
        margin = JBUI.insets(6)
    }

    private val status = JBLabel("")

    init {
        val provenance = buildString {
            append(proposal.backend)
            proposal.engine?.let { append(" · ").append(it) }
            proposal.pagePath?.let { append(" · ").append(it.substringAfterLast('/')) }
        }
        add(JBLabel(provenance).apply { border = JBUI.Borders.empty(4, 8) }, BorderLayout.NORTH)
        add(JBScrollPane(textArea), BorderLayout.CENTER)

        val buttons = JPanel(FlowLayout(FlowLayout.LEFT))
        val apply = JButton("Apply to Linked Range").apply {
            isEnabled = proposal.applyToTarget != null
            addActionListener {
                val error = proposal.applyToTarget?.invoke(textArea.text)
                status.text = error ?: "Applied."
                if (error == null) {
                    isEnabled = false
                }
            }
        }
        buttons.add(apply)
        buttons.add(JButton("Copy").apply {
            addActionListener {
                CopyPasteManager.getInstance().setContents(StringSelection(textArea.text))
                status.text = "Copied to clipboard."
            }
        })
        buttons.add(status)
        add(buttons, BorderLayout.SOUTH)
    }
}
