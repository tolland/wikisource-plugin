package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.TextEditorWithPreview

/**
 * Base of the wikitext split editors. One concrete subclass exists per
 * [WtEditorProfile] — [WtPreviewEditorProvider] picks it from the file's
 * MediaWiki content model. Shared wiring lives here; the subclasses are where
 * per-model behavior (ProofreadPage header/footer handling, index-specific
 * forms, …) grows.
 *
 * The preview pane carries its own inset [WtPreviewToolbar] (mode toggle /
 * reload / zoom / OCR) instead of actions on the platform's hover toolbar.
 * Page navigation is a proofread-page concern and lives in
 * [WtProofreadFormTextEditor]'s toolbar, above the header/body/footer form
 * and the raw-mode toggle it belongs with.
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
