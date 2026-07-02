package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditor
import com.intellij.openapi.fileEditor.FileEditorState
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.util.UserDataHolderBase
import com.intellij.openapi.vfs.VfsUtilCore
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.ui.components.JBPanel
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.backend.PreviewResult
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.awt.BorderLayout
import java.beans.PropertyChangeListener
import java.util.concurrent.atomic.AtomicLong
import javax.swing.JComponent
import javax.swing.JEditorPane
import javax.swing.Timer

private val PREVIEW_LOG = logger<WtRenderPreviewBrowser>()

/**
 * Preview half of the wikitext split editor.
 *
 * Rendering is delegated to the wiki itself: the current (unsaved) document
 * text goes to the wtbot sidecar's `POST /preview/render`, which proxies
 * MediaWiki's `action=parse` — the same API the browser's live preview uses —
 * so templates, ProofreadPage quality headers, and site CSS all match what a
 * save would produce. The returned HTML is shown in a JCEF browser (falling
 * back to a Swing [JEditorPane] where JCEF is unavailable).
 */
class WtRenderPreviewBrowser(
    private val file: VirtualFile,
) : UserDataHolderBase(), FileEditor, Disposable {
    private val component = JBPanel<JBPanel<*>>(BorderLayout())

    private val jcefBrowser: JBCefBrowser? =
        if (JBCefApp.isSupported()) {
            JBCefBrowser().also { Disposer.register(this, it) }
        } else {
            null
        }

    // Swing's HTML support is far behind the wiki's markup — used only where
    // JCEF is unavailable (e.g. some remote-dev/headless setups).
    private val fallbackPane: JEditorPane? =
        if (jcefBrowser == null) {
            JEditorPane("text/html", "").apply { isEditable = false }
        } else {
            null
        }

    // Debounce keystrokes: every reload is a network round trip through the
    // sidecar to the wiki, so wait for a typing pause rather than 250ms.
    private val reloadTimer = Timer(500) { reloadPreview() }.apply {
        isRepeats = false
    }

    // Monotonic request id — a stale response never overwrites a newer one.
    private val requestGeneration = AtomicLong(0)

    @Volatile
    private var disposed = false

    init {
        val viewer: JComponent = jcefBrowser?.component ?: JBScrollPane(fallbackPane)
        component.add(viewer, BorderLayout.CENTER)
        reloadPreview()

        FileDocumentManager.getInstance().getDocument(file)?.addDocumentListener(object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) {
                scheduleReload()
            }
        }, this)
    }

    private fun scheduleReload() {
        if (!disposed) {
            reloadTimer.restart()
        }
    }

    fun reloadPreview() {
        if (disposed) {
            return
        }

        val wikitext = readWikitext()
        val generation = requestGeneration.incrementAndGet()

        ApplicationManager.getApplication().executeOnPooledThread {
            val html = try {
                shellHtml(WtVfsService.instance.backend.renderPreview(
                    path = (file as? WtVirtualFile)?.path,
                    title = if (file is WtVirtualFile) null else file.nameWithoutExtension,
                    wikitext = wikitext,
                ))
            } catch (e: Exception) {
                PREVIEW_LOG.warn("wikitext preview render failed for ${file.path}", e)
                errorHtml(e.message ?: e.javaClass.simpleName)
            }
            ApplicationManager.getApplication().invokeLater {
                if (!disposed && generation == requestGeneration.get()) {
                    showHtml(html)
                }
            }
        }
    }

    private fun readWikitext(): String {
        val document = FileDocumentManager.getInstance().getDocument(file)
        return document?.text ?: VfsUtilCore.loadText(file)
    }

    private fun showHtml(html: String) {
        val browser = jcefBrowser
        if (browser != null) {
            browser.loadHTML(html)
        } else {
            fallbackPane?.text = html
            fallbackPane?.caretPosition = 0
        }
    }

    /**
     * Wraps the parser's HTML fragment in a document that pulls the wiki's own
     * stylesheets (site.styles carries the skin-independent content CSS;
     * ext.proofreadpage.base styles the Page-quality banner) and rebases
     * relative links/images onto the wiki server.
     */
    private fun shellHtml(result: PreviewResult): String {
        val stylesheet = if (result.server != null && result.scriptPath != null) {
            val load = "${result.server}${result.scriptPath}/load.php" +
                "?modules=site.styles%7Cext.proofreadpage.base&only=styles"
            """<base href="${result.server}/"><link rel="stylesheet" href="$load">"""
        } else {
            ""
        }
        return """
            <!DOCTYPE html>
            <html>
            <head>
            <meta charset="utf-8">
            $stylesheet
            <style>
              body { font-family: sans-serif; margin: 12px;
                     background: #fff; color: #202122; }
            </style>
            </head>
            <body>${result.decodeHtml()}</body>
            </html>
        """.trimIndent()
    }

    private fun errorHtml(message: String): String {
        val escaped = message
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        return """
            <!DOCTYPE html>
            <html>
            <head><meta charset="utf-8"></head>
            <body style="font-family: sans-serif; margin: 12px;">
            <p><b>Preview unavailable</b></p>
            <p>$escaped</p>
            <p style="color: #54595d;">Is the wtbot sidecar running?</p>
            </body>
            </html>
        """.trimIndent()
    }

    override fun getComponent(): JComponent = component

    override fun getPreferredFocusedComponent(): JComponent =
        jcefBrowser?.component ?: fallbackPane!!

    override fun getName(): String = "Wikitext Preview"

    override fun setState(state: FileEditorState) = Unit

    override fun isModified(): Boolean = false

    override fun isValid(): Boolean = !disposed && file.isValid

    override fun addPropertyChangeListener(listener: PropertyChangeListener) = Unit

    override fun removePropertyChangeListener(listener: PropertyChangeListener) = Unit

    override fun getFile(): VirtualFile = file

    override fun dispose() {
        disposed = true
        reloadTimer.stop()
    }
}
