package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.vfs.VirtualFile
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService

/**
 * The reference-scan half of the proofread preview. The scan is independent
 * of the document text, so it is loaded once — lazily, on first show — and
 * the browser (with its zoom and scroll state) is kept alive across mode
 * toggles rather than being re-fetched every time.
 */
class WtReferenceImagePane(
    private val file: VirtualFile,
) : WtBrowserPane() {
    private var loaded = false

    /** Loads the scan on first call; later calls reuse the loaded browser. */
    fun ensureLoaded() {
        if (!loaded) {
            loaded = true
            // Building the URL is local; JCEF fetches the image itself.
            showHtml(referenceImageHtml())
        }
    }

    private fun referenceImageHtml(): String {
        val url = WtVfsService.instance.backend.pageImageUrl(
            (file as? WtVirtualFile)?.path,
            if (file is WtVirtualFile) null else file.nameWithoutExtension,
        )
        return """
            <!DOCTYPE html>
            <html>
            <head><meta charset="utf-8"></head>
            <body style="margin: 0; background: #3c3f41; text-align: center;">
            <img src="$url" alt="reference scan"
                 style="max-width: 100%; height: auto; margin: 12px auto;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.5);">
            </body>
            </html>
        """.trimIndent()
    }
}
