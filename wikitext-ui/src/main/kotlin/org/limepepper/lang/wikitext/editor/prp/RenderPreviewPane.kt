package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.application.runReadActionBlocking
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.vfs.VfsUtilCore
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser
import com.intellij.ui.jcef.JBCefJSQuery
import org.limepepper.lang.wikitext.preview.JcefBrowserZoom
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.backend.PreviewResult
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.util.concurrent.atomic.AtomicLong
import javax.swing.JComponent
import javax.swing.JEditorPane
import javax.swing.Timer

private val PREVIEW_LOG = logger<RenderPreviewPane>()

/**
 * The rendered-HTML half of the preview: sends the current (unsaved) document
 * text to the wtbot sidecar's `POST /preview/render`, which proxies
 * MediaWiki's `action=parse` — the same API the browser's live preview uses —
 * so templates, ProofreadPage quality headers, and site CSS all match what a
 * save would produce. The HTML is shown in a JCEF browser, falling back to a
 * Swing [JEditorPane] where JCEF is unavailable (some remote-dev and headless
 * setups) — Swing's own HTML support is far behind the wiki's markup.
 */
class RenderPreviewPane(
    private val file: VirtualFile,
) : Disposable {
    private val jcefBrowser: JBCefBrowser? =
        if (JBCefApp.isSupported()) {
            JBCefBrowser().also { Disposer.register(this, it) }
        } else {
            null
        }

    private val fallbackPane: JEditorPane? =
        if (jcefBrowser == null) {
            JEditorPane("text/html", "").apply { isEditable = false }
        } else {
            null
        }

    val component: JComponent = jcefBrowser?.component ?: JBScrollPane(fallbackPane)

    // Ctrl-wheel zoom, with the level held across reloads; also drives the
    // toolbar zoom buttons so wheel and buttons share one zoom level.
    private val zoom: JcefBrowserZoom? = jcefBrowser?.let { JcefBrowserZoom(it) }

    /** True when zoom controls apply (JCEF present; the Swing fallback has none). */
    val zoomSupported: Boolean
        get() = zoom != null

    fun zoomIn() = zoom?.zoomIn() ?: Unit

    fun zoomOut() = zoom?.zoomOut() ?: Unit

    fun resetZoom() = zoom?.resetZoom() ?: Unit

    // Latest vertical scroll offset the page reported, so a reload (which goes
    // through loadHTML and would otherwise jump back to the top) can restore
    // roughly where the reader was. The page reports it via [scrollQuery]; the
    // restore is injected into each rendered document (see [shellHtml]).
    @Volatile
    private var lastScrollY: Int = 0

    private val scrollQuery: JBCefJSQuery? = jcefBrowser?.let { browser ->
        JBCefJSQuery.create(browser as com.intellij.ui.jcef.JBCefBrowserBase).also { query ->
            query.addHandler { value ->
                value.toDoubleOrNull()?.let { lastScrollY = it.toInt() }
                null
            }
            Disposer.register(this, query)
        }
    }

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
    var visible: Boolean = false
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
        runReadActionBlocking {
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
            $scrollScript
            </head>
            <body>${result.decodeHtml()}</body>
            </html>
        """.trimIndent()
    }

    /**
     * Script injected into every rendered document to (a) report the vertical
     * scroll offset back to [scrollQuery] as the reader scrolls, and (b) restore
     * the last reported offset once this reload finishes loading — the browser
     * clamps an out-of-range offset to the new content height, so a preview that
     * shrank simply lands at the bottom rather than off the end. Empty when JCEF
     * (and thus the query) is unavailable.
     */
    private val scrollScript: String
        get() {
            val query = scrollQuery ?: return ""
            val report = query.inject("String(window.scrollY)")
            return """
                <script>
                  (function() {
                    var pending;
                    window.addEventListener('scroll', function() {
                      clearTimeout(pending);
                      pending = setTimeout(function() { $report }, 100);
                    }, { passive: true });
                    window.addEventListener('load', function() {
                      window.scrollTo(0, $lastScrollY);
                    });
                  })();
                </script>
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

    private fun showHtml(html: String) {
        val browser = jcefBrowser
        if (browser != null) {
            browser.loadHTML(html)
        } else {
            fallbackPane?.text = html
            fallbackPane?.caretPosition = 0
        }
    }

    override fun dispose() {
        disposed = true
        reloadTimer.stop()
    }
}
