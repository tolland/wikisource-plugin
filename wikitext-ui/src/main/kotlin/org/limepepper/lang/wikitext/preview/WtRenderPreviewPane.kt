package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.application.ReadAction
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.vfs.VfsUtilCore
import com.intellij.openapi.vfs.VirtualFile
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.backend.PreviewResult
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.util.concurrent.atomic.AtomicLong
import javax.swing.Timer

private val PREVIEW_LOG = logger<WtRenderPreviewPane>()

/**
 * The rendered-HTML half of the preview: sends the current (unsaved) document
 * text to the wtbot sidecar's `POST /preview/render`, which proxies
 * MediaWiki's `action=parse` — the same API the browser's live preview uses —
 * so templates, ProofreadPage quality headers, and site CSS all match what a
 * save would produce.
 */
class WtRenderPreviewPane(
    private val file: VirtualFile,
) : WtBrowserPane() {
    // Debounce keystrokes: every reload is a network round trip through the
    // sidecar to the wiki, so wait for a typing pause rather than 250ms.
    private val reloadTimer = Timer(500) { reload() }.apply {
        isRepeats = false
    }

    // Monotonic request id — a stale response never overwrites a newer one.
    private val requestGeneration = AtomicLong(0)

    @Volatile
    private var disposed = false

    // Edits arriving while the pane is hidden (reference image showing) are
    // coalesced into one reload on the next show instead of rendering into an
    // invisible browser on every typing pause.
    private var pendingReload = false

    /** Set by the owning editor when this pane is shown/hidden. */
    var visible: Boolean = true
        set(value) {
            field = value
            if (value && pendingReload) {
                pendingReload = false
                reload()
            }
        }

    fun scheduleReload() {
        if (disposed) {
            return
        }
        if (visible) {
            reloadTimer.restart()
        } else {
            pendingReload = true
        }
    }

    fun reload() {
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

    /**
     * Runs in an explicit read action: callers include the Swing debounce
     * [Timer], which fires on the EDT but — like any raw Swing callback on a
     * modern platform — without the implicit read lock that IDE actions get.
     */
    private fun readWikitext(): String =
        ReadAction.compute<String, RuntimeException> {
            val document = FileDocumentManager.getInstance().getDocument(file)
            document?.text ?: VfsUtilCore.loadText(file)
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

    override fun dispose() {
        disposed = true
        reloadTimer.stop()
        super.dispose()
    }
}
