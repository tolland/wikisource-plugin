package org.limepepper.lang.wikitext.preview

import com.intellij.codeHighlighting.BackgroundEditorHighlighter
import com.intellij.ide.structureView.StructureViewBuilder
import com.intellij.openapi.actionSystem.ActionGroup
import com.intellij.openapi.fileEditor.FileEditorLocation
import com.intellij.openapi.fileEditor.FileEditorState
import com.intellij.openapi.fileEditor.FileEditorStateLevel
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.vfs.VirtualFile
import org.jetbrains.annotations.Unmodifiable
import java.awt.BorderLayout
import java.awt.CardLayout
import javax.swing.JComponent
import javax.swing.JPanel


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

    /** The form's body (transcription) editor — see [WtProofreadPageForm.bodySectionEditor]. */
    val bodyEditor
        get() = form.bodySectionEditor

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

    override fun getState(level: FileEditorStateLevel): FileEditorState {
        return delegate.getState(level)
    }

    override fun setState(state: FileEditorState, exactState: Boolean) {
        delegate.setState(state, exactState)
    }

    override fun selectNotify() {
        delegate.selectNotify()
    }

    override fun deselectNotify() {
        delegate.deselectNotify()
    }

    override fun getBackgroundHighlighter(): BackgroundEditorHighlighter? {
        return delegate.backgroundHighlighter
    }

    override fun getCurrentLocation(): FileEditorLocation? {
        return delegate.currentLocation
    }

    override fun getStructureViewBuilder(): StructureViewBuilder? {
        return delegate.structureViewBuilder
    }

    // Kotlin interface delegation only implements *abstract* members, so the
    // platform's deprecated default getFile() (which logs a PluginException)
    // was still in effect here — a @NotNull override is required.
    override fun getFile(): VirtualFile = delegate.file
    override fun getFilesToRefresh(): @Unmodifiable List<VirtualFile> {
        return delegate.filesToRefresh
    }

    override fun getTabActions(): ActionGroup? {
        return delegate.tabActions
    }

    override fun dispose() {
        Disposer.dispose(form)
        Disposer.dispose(delegate)
    }

    private companion object {
        const val CARD_FORM = "form"
        const val CARD_RAW = "raw"
    }
}
