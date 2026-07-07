package org.limepepper.lang.wikitext.preview

import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.ToggleAction
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.vfs.VirtualFile
import java.awt.BorderLayout
import java.awt.CardLayout
import javax.swing.JComponent
import javax.swing.JPanel

/**
 * Editor for `proofread-page` bodies (transcriptions). The editor half is not
 * the raw serialized buffer but a [WtProofreadPageForm] — separate header,
 * body, and footer fields plus the page-quality control, the desktop
 * equivalent of the wiki's ProofreadPage edit form. The form keeps the file's
 * single `<noinclude><pagequality …/>header</noinclude>body<noinclude>footer</noinclude>`
 * buffer as the source of truth (so save, PSI, and the preview are unaffected)
 * and edits it through [ProofreadPageParts]; the underlying [TextEditor] stays
 * live to back the document, state, and navigation machinery, and can be
 * brought on screen with the raw-mode toggle in the toolbar.
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
 * A [TextEditor] that presents the proofread editing surface as its UI while
 * delegating everything else (document, file, state) to the real [delegate]
 * editor, so [WtProofreadPageEditor] can plug the form into
 * [com.intellij.openapi.fileEditor.TextEditorWithPreview]'s editor slot
 * without giving up the platform's text-editor plumbing.
 *
 * The surface is a card stack under one shared toolbar (page navigation +
 * the raw-mode toggle):
 *
 *  - **form card** (default): the three-field [WtProofreadPageForm];
 *  - **raw card**: the delegate's plain text editor over the serialized
 *    buffer, for when the structured view gets in the way (or the buffer is
 *    malformed and needs hand-repair). Both cards edit the same document, so
 *    switching is always in sync and never loses work.
 */
class WtProofreadFormTextEditor(
    project: Project,
    private val delegate: TextEditor,
) : TextEditor by delegate {
    private val form = WtProofreadPageForm(project, delegate)

    private val cards = CardLayout()
    private val cardPanel = JPanel(cards)
    private val wrapper = JPanel(BorderLayout())

    /** `true` shows the raw serialized buffer in the plain text editor. */
    var rawMode: Boolean = false
        set(value) {
            if (field == value) return
            field = value
            cards.show(cardPanel, if (value) CARD_RAW else CARD_FORM)
            preferredFocusedComponent.requestFocusInWindow()
        }

    init {
        cardPanel.add(form.component, CARD_FORM)
        cardPanel.add(delegate.component, CARD_RAW)
        val toolbar = WtPageNavToolbar(cardPanel, delegate.file, listOf(ToggleRawModeAction(this)))
        wrapper.add(toolbar.component, BorderLayout.NORTH)
        wrapper.add(cardPanel, BorderLayout.CENTER)
    }

    override fun getComponent(): JComponent = wrapper

    override fun getPreferredFocusedComponent(): JComponent =
        if (rawMode) {
            delegate.preferredFocusedComponent ?: delegate.editor.contentComponent
        } else {
            form.preferredFocusComponent
        }

    // Kotlin interface delegation only implements *abstract* members, so the
    // platform's deprecated default getFile() (which logs a PluginException)
    // was still in effect here — a @NotNull override is required.
    override fun getFile(): VirtualFile = delegate.file

    override fun dispose() {
        Disposer.dispose(form)
        Disposer.dispose(delegate)
    }

    private companion object {
        const val CARD_FORM = "form"
        const val CARD_RAW = "raw"
    }
}

/** Flips [WtProofreadFormTextEditor] between the three-field form and the raw buffer. */
private class ToggleRawModeAction(
    private val editor: WtProofreadFormTextEditor,
) : ToggleAction(
    "Edit Raw Page Text",
    "Edit the serialized <noinclude> form directly instead of the header/body/footer fields",
    AllIcons.Actions.ToggleVisibility,
) {
    override fun isSelected(event: AnActionEvent): Boolean = editor.rawMode

    override fun setSelected(event: AnActionEvent, state: Boolean) {
        editor.rawMode = state
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}
