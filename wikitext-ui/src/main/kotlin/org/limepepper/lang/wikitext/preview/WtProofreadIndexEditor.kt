package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.fileEditor.TextEditor

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
