package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.editor.ex.EditorEx
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.TextEditorWithPreview

/**
 * Base of the wikitext split editors. One concrete subclass exists per
 * [WtEditorProfile] — [WtPreviewEditorProvider] picks it from the file's
 * MediaWiki content model. Shared wiring lives here; the subclasses are the
 * stubs where per-model behavior (ProofreadPage header/footer handling,
 * index-specific forms, …) will grow.
 *
 * Both halves carry their own inset toolbar instead of actions on the
 * platform's hover toolbar: the preview pane owns [WtPreviewToolbar]
 * (mode toggle / reload / zoom / OCR) and, for profiles with page
 * navigation, the text editor gets [WtPageNavToolbar] as its header
 * component (page back/forward).
 */
sealed class WtEditorWithPreview(
    textEditor: TextEditor,
    wtPreviewEditor: WtRenderPreviewBrowser,
    name: String,
    profile: WtEditorProfile,
) : TextEditorWithPreview(
    textEditor,
    wtPreviewEditor,
    name,
    Layout.SHOW_EDITOR_AND_PREVIEW,
) {
    init {
        // Initialize TextEditorWithPreview's lazy UI before disposal-sensitive editor switching can occur.
        component

        if (profile.hasPageNavigation) {
            (textEditor.editor as? EditorEx)?.let { editor ->
                val navBar = WtPageNavToolbar(editor.component).component
                // Permanent so the row comes back when the find bar (which
                // shares the header slot) is closed.
                editor.permanentHeaderComponent = navBar
                editor.headerComponent = navBar
            }
        }
    }
}

/** Fallback editor for plain `wikitext` (and unknown content models) — no restrictions. */
class WtWikitextEditor(
    textEditor: TextEditor,
    wtPreviewEditor: WtRenderPreviewBrowser,
) : WtEditorWithPreview(
    textEditor,
    wtPreviewEditor,
    "Wikitext Editor",
    WtEditorProfile.WIKITEXT,
)
