package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import javax.swing.JComponent

/**
 * A [com.intellij.openapi.fileEditor.TextEditor] that presents [WtProofreadPageForm] as its UI while delegating
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
