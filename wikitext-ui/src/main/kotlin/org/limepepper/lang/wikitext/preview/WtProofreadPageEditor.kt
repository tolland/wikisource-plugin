package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import javax.swing.JComponent

/**
 * Editor for `proofread-page` bodies (transcriptions). The editor half is not
 * the raw serialized buffer but a [WtProofreadPageForm] — separate header,
 * body, and footer fields, the desktop equivalent of the wiki's ProofreadPage
 * edit form. The form keeps the file's single
 * `<noinclude>header</noinclude>body<noinclude>footer</noinclude>` buffer as
 * the source of truth (so save, PSI, and the preview are unaffected) and edits
 * it through [ProofreadPageParts]; the underlying [TextEditor] stays live but
 * off-screen to back the document, state, and navigation machinery.
 */
class WtProofreadPageEditor private constructor(
    editorHalf: WtProofreadFormTextEditor,
    previewEditor: WtRenderPreviewBrowser,
) : WtEditorWithPreview(
    editorHalf,
    previewEditor,
    "Proofread Page Editor",
    WtEditorProfile.PROOFREAD_PAGE,
) {
    constructor(project: Project, textEditor: TextEditor, previewEditor: WtRenderPreviewBrowser) :
        this(WtProofreadFormTextEditor(project, textEditor), previewEditor)
}

/**
 * A [TextEditor] that presents [WtProofreadPageForm] as its UI while delegating
 * everything else (document, file, state, focus wiring behind the scenes) to
 * the real [delegate] editor. This lets [WtProofreadPageEditor] plug the
 * three-field form into [TextEditorWithPreview]'s editor slot without giving up
 * the platform's text-editor plumbing.
 */
class WtProofreadFormTextEditor(
    project: Project,
    private val delegate: TextEditor,
) : TextEditor by delegate {
    private val form = WtProofreadPageForm(project, delegate)

    override fun getComponent(): JComponent = form.component

    override fun getPreferredFocusedComponent(): JComponent = form.preferredFocusComponent

    override fun dispose() {
        Disposer.dispose(form)
        Disposer.dispose(delegate)
    }
}
