package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.Disposable
import com.intellij.openapi.util.Disposer
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser
import org.cef.browser.CefBrowser
import org.cef.browser.CefFrame
import org.cef.handler.CefLoadHandlerAdapter
import javax.swing.JComponent
import javax.swing.JEditorPane

/**
 * A browser surface shared by the preview panes: a JCEF browser where
 * available, a Swing [JEditorPane] fallback otherwise (some remote-dev and
 * headless setups). Each pane owns its own browser instance, so per-pane
 * state — loaded content, scroll position, zoom — survives switching between
 * panes without a reload.
 *
 * Zoom notes (JCEF only):
 *  - [JBCefBrowser.setZoomLevel] takes a plain scale factor (1.0 = 100%) and
 *    converts to CEF's logarithmic zoom level internally — do not pre-convert
 *    (raw CEF `CefBrowser.setZoomLevel` is the API that takes the log level).
 *  - CEF resets the zoom whenever a navigation commits, and `loadHTML` is
 *    asynchronous — setting the zoom right after it is a lost update. The
 *    pane re-applies the zoom from an `onLoadEnd` handler instead.
 */
abstract class WtBrowserPane : Disposable {
    protected val jcefBrowser: JBCefBrowser? =
        if (JBCefApp.isSupported()) {
            JBCefBrowser().also { Disposer.register(this, it) }
        } else {
            null
        }

    // Swing's HTML support is far behind the wiki's markup — fallback only.
    private val fallbackPane: JEditorPane? =
        if (jcefBrowser == null) {
            JEditorPane("text/html", "").apply { isEditable = false }
        } else {
            null
        }

    val component: JComponent = jcefBrowser?.component ?: JBScrollPane(fallbackPane)

    val isZoomSupported: Boolean
        get() = jcefBrowser != null

    /** User-facing zoom scale: 1.0 = 100%. */
    var zoomScale: Double = 1.0
        private set

    init {
        jcefBrowser?.let { browser ->
            browser.jbCefClient.addLoadHandler(object : CefLoadHandlerAdapter() {
                override fun onLoadEnd(cefBrowser: CefBrowser, frame: CefFrame, httpStatusCode: Int) {
                    applyZoom()
                }
            }, browser.cefBrowser)
        }
    }

    fun zoomBy(factor: Double) {
        zoomScale = (zoomScale * factor).coerceIn(MIN_ZOOM, MAX_ZOOM)
        applyZoom()
    }

    fun resetZoom() {
        zoomScale = 1.0
        applyZoom()
    }

    private fun applyZoom() {
        jcefBrowser?.setZoomLevel(zoomScale)
    }

    protected fun showHtml(html: String) {
        val browser = jcefBrowser
        if (browser != null) {
            browser.loadHTML(html)
        } else {
            fallbackPane?.text = html
            fallbackPane?.caretPosition = 0
        }
    }

    override fun dispose() = Unit

    private companion object {
        const val MIN_ZOOM = 0.2
        const val MAX_ZOOM = 8.0
    }
}
