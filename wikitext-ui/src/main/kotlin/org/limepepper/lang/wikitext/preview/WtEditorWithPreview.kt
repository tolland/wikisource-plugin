package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.TextEditorWithPreview

/**
 * Base of the wikitext split editors. One concrete subclass exists per
 * [WtEditorProfile] — [WtPreviewEditorProvider] picks it from the file's
 * MediaWiki content model. Shared wiring lives here; the subclasses are where
 * per-model behavior (index-specific forms, …) grows.
 *
 * The preview pane carries its own inset [WtPreviewToolbar] (reload) instead
 * of actions on the platform's hover toolbar.
 */
open class WtEditorWithPreview(
    textEditor: TextEditor,
    wtPreviewEditor: WtRenderPreviewBrowser,
    name: String,
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
)
