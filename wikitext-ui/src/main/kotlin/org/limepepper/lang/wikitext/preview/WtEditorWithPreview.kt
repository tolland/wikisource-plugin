package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.editor.ex.EditorEx
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.TextEditorWithPreview
import com.intellij.openapi.fileEditor.TextEditorWithPreview.Layout

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

/**
 * Editor for `proofread-page` bodies (transcriptions). Has a reference scan
 * and page back/forward navigation. The body convention
 * `<noinclude>header</noinclude>body<noinclude>footer</noinclude>` must be
 * preserved across edits — currently the buffer simply holds the serialized
 * form verbatim; dedicated header/body/footer handling (like the web
 * editor's three fields) is future work anchored here.
 */
class WtProofreadPageEditor(
    textEditor: TextEditor,
    wtPreviewEditor: WtRenderPreviewBrowser,
) : WtEditorWithPreview(
    textEditor,
    wtPreviewEditor,
    "Proofread Page Editor",
    WtEditorProfile.PROOFREAD_PAGE,
)

/**
 * Editor for `proofread-index` bodies. No reference scan of its own; the
 * wiki renders the body through `{{:MediaWiki:Proofreadpage_index_template}}`,
 * which the preview already reflects (the sidecar passes the content model
 * to `action=parse`). Index-specific affordances (field-level editing of the
 * template invocation, pagelist tooling, …) are future work anchored here.
 */
class WtProofreadIndexEditor(
    textEditor: TextEditor,
    wtPreviewEditor: WtRenderPreviewBrowser,
) : WtEditorWithPreview(
    textEditor,
    wtPreviewEditor,
    "Proofread Index Editor",
    WtEditorProfile.PROOFREAD_INDEX,
)

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
