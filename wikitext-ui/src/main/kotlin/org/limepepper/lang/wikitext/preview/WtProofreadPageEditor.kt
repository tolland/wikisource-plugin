package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.fileEditor.TextEditor

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
