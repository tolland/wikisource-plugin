package org.limepepper.lang.wikitext.preview

import com.intellij.ui.jcef.JBCefBrowser
import org.cef.browser.CefBrowser
import org.cef.browser.CefFrame
import org.cef.handler.CefLoadHandlerAdapter
import java.awt.Component
import java.awt.Container
import java.awt.event.ContainerAdapter
import java.awt.event.ContainerEvent
import java.awt.event.MouseWheelListener

/**
 * Ctrl-wheel (Cmd-wheel on mac) zoom for a JCEF preview browser.
 *
 * Chromium's zoom API is denominated in *zoom levels*, not scale factors:
 * the rendered scale is 1.2^level, so +1 level is 120% and -1 is ~83% —
 * feeding [CefBrowser.setZoomLevel] a scale factor directly zooms wildly.
 * The wheel is therefore handled on the Swing side and mapped into level
 * units, and the level is re-applied after every navigation because
 * `loadHTML()` (which every preview reload goes through) resets Chromium
 * back to 100%.
 *
 * Plain and Shift-wheel scrolling are left to the browser, which already
 * follows the vertical/horizontal convention.
 */
class JcefBrowserZoom(private val browser: JBCefBrowser) {
    private var level = 0.0

    private val wheelListener = MouseWheelListener { e ->
        if (e.isControlDown || e.isMetaDown) {
            e.consume()
            zoomBy(-e.preciseWheelRotation * LEVEL_PER_NOTCH)
        }
    }

    init {
        browser.jbCefClient.addLoadHandler(object : CefLoadHandlerAdapter() {
            override fun onLoadEnd(cefBrowser: CefBrowser, frame: CefFrame?, httpStatusCode: Int) {
                cefBrowser.zoomLevel = level
            }
        }, browser.cefBrowser)
        installOn(browser.component)
    }

    /**
     * The wheel must be caught on whichever descendant actually receives
     * mouse events (OSR canvas or windowed wrapper), and the browser builds
     * its Swing subtree lazily — so cover the whole tree, present and future.
     */
    private fun installOn(component: Component) {
        component.addMouseWheelListener(wheelListener)
        if (component is Container) {
            component.components.forEach(::installOn)
            component.addContainerListener(object : ContainerAdapter() {
                override fun componentAdded(e: ContainerEvent) = installOn(e.child)
            })
        }
    }

    private fun zoomBy(deltaLevels: Double) {
        level = (level + deltaLevels).coerceIn(MIN_LEVEL, MAX_LEVEL)
        browser.cefBrowser.zoomLevel = level
    }

    private companion object {
        /** Zoom levels per wheel notch: 0.5 ≈ ±9.5% per notch. */
        const val LEVEL_PER_NOTCH = 0.5

        /** 1.2^-4 ≈ 48% and 1.2^8 ≈ 430%. */
        const val MIN_LEVEL = -4.0
        const val MAX_LEVEL = 8.0
    }
}
