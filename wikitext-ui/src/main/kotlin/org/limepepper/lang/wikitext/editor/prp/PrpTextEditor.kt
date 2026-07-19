package org.limepepper.lang.wikitext.editor.prp

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

class PrpTextEditor(
    project: Project,
    private val delegate: TextEditor,
) : TextEditor by delegate  {

    private val form = PrpPageForm(project, delegate)

    /** The form's body (transcription) editor — see [PrpPageForm.bodySectionEditor]. */
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

    override fun isEditorLoaded(): Boolean {
        return delegate.isEditorLoaded()
    }

    private companion object {
        const val CARD_FORM = "form"
        const val CARD_RAW = "raw"
    }
}
