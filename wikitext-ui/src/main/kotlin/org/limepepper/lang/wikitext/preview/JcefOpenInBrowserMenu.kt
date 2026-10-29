package org.limepepper.lang.wikitext.preview

import com.intellij.ide.BrowserUtil
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.ui.jcef.JBCefBrowser
import org.cef.browser.CefBrowser
import org.cef.browser.CefFrame
import org.cef.callback.CefContextMenuParams
import org.cef.callback.CefMenuModel
import org.cef.handler.CefContextMenuHandlerAdapter
import java.nio.file.Files
import java.nio.file.Path

private val MENU_LOG = logger<JcefOpenInBrowserMenu>()

/**
 * Adds "Open in Browser" to a JCEF preview's right-click menu.
 *
 * When [urlProvider] yields a URL (a `wikisource://` file, served by the
 * sidecar's `GET /preview/view`) the system browser opens that, so a refresh
 * re-renders the saved body plus uncommitted journal entries. Otherwise (local
 * scratch files) the currently shown document is written to a temp file — a
 * snapshot that doesn't reload, though its `<base href>` and stylesheet links
 * are absolute so it renders as in the pane.
 *
 * @param urlProvider the browser-openable URL for the file, or null.
 * @param htmlProvider the full HTML document currently displayed, or null if
 *   nothing has rendered yet.
 */
class JcefOpenInBrowserMenu(
    browser: JBCefBrowser,
    private val urlProvider: () -> String?,
    private val htmlProvider: () -> String?,
) {
    private val tempFile: Path by lazy {
        Files.createTempFile("wikitext-preview-", ".html").also { it.toFile().deleteOnExit() }
    }

    init {
        browser.jbCefClient.addContextMenuHandler(object : CefContextMenuHandlerAdapter() {
            override fun onBeforeContextMenu(
                cefBrowser: CefBrowser,
                frame: CefFrame?,
                params: CefContextMenuParams?,
                model: CefMenuModel,
            ) {
                if (model.count > 0) {
                    model.addSeparator()
                }
                model.addItem(COMMAND_ID, "Open in Browser")
            }

            override fun onContextMenuCommand(
                cefBrowser: CefBrowser,
                frame: CefFrame?,
                params: CefContextMenuParams?,
                commandId: Int,
                eventFlags: Int,
            ): Boolean {
                if (commandId != COMMAND_ID) {
                    return false
                }
                openInBrowser()
                return true
            }
        }, browser.cefBrowser)
    }

    private fun openInBrowser() {
        ApplicationManager.getApplication().executeOnPooledThread {
            try {
                val url = urlProvider()
                if (url != null) {
                    BrowserUtil.browse(url)
                    return@executeOnPooledThread
                }
                val html = htmlProvider() ?: return@executeOnPooledThread
                Files.writeString(tempFile, html)
                BrowserUtil.browse(tempFile.toUri())
            } catch (e: Exception) {
                MENU_LOG.warn("could not open wikitext preview in external browser", e)
            }
        }
    }

    private companion object {
        /** Must lie in CEF's user-command range (MENU_ID_USER_FIRST = 26500). */
        const val COMMAND_ID = 26500
    }
}
