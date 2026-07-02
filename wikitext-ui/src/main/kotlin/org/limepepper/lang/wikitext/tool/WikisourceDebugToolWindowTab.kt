package org.limepepper.lang.wikitext.tool

import com.intellij.openapi.application.ApplicationManager
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.awt.BorderLayout
import javax.swing.JButton
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.SwingUtilities

internal class WikisourceDebugToolWindowTab {

    fun createComponent(): JPanel {
        val statusLabel = JLabel("Status: checking…")
        val infoArea = JBTextArea(20, 60).apply {
            isEditable = false
            font = java.awt.Font(java.awt.Font.MONOSPACED, java.awt.Font.PLAIN, 12)
        }
        val refreshButton = JButton("Refresh").apply {
            addActionListener {
                ApplicationManager.getApplication().executeOnPooledThread {
                    checkBackend(statusLabel, infoArea)
                }
            }
        }
        val top = JPanel(BorderLayout())
        top.add(statusLabel, BorderLayout.CENTER)
        top.add(refreshButton, BorderLayout.EAST)

        val panel = JPanel(BorderLayout())
        panel.add(top, BorderLayout.NORTH)
        panel.add(JBScrollPane(infoArea), BorderLayout.CENTER)

        ApplicationManager.getApplication().executeOnPooledThread {
            checkBackend(statusLabel, infoArea)
        }
        return panel
    }

    private fun checkBackend(label: JLabel, area: JBTextArea) {
        val backend = WtVfsService.instance.backend
        try {
            val root = backend.stat("/")
            val sites = backend.listChildren("/")
            val sb = StringBuilder()
            sb.appendLine("stat /  →  exists=${root.exists}  kind=${root.kind}")
            sb.appendLine()
            sb.appendLine("Sites (${sites.children.size}):")
            for (site in sites.children) {
                sb.appendLine("  ${site.path}  [${site.kind}]  stableId=${site.stableId}")
                try {
                    val indexes = backend.listChildren(site.path)
                    for (idx in indexes.children) {
                        sb.appendLine("    ${idx.name}  [${idx.kind}]  stableId=${idx.stableId}")
                        try {
                            val containers = backend.listChildren(idx.path)
                            for (c in containers.children) {
                                sb.appendLine("      ${c.name}  [${c.kind}]")
                            }
                        } catch (_: VfsBackendException) {
                        }
                    }
                } catch (_: VfsBackendException) {
                }
            }
            SwingUtilities.invokeLater {
                label.text = "Status: ✓ connected"
                area.text = sb.toString()
            }
        } catch (e: VfsBackendException) {
            SwingUtilities.invokeLater {
                label.text = "Status: ✗ offline — ${e.message}"
                area.text = ""
            }
        }
    }
}
