package org.limepepper.lang.wikitext.editor.prp

import com.intellij.codeHighlighting.BackgroundEditorHighlighter
import com.intellij.ide.structureView.StructureViewBuilder
import com.intellij.openapi.actionSystem.ActionGroup
import com.intellij.openapi.editor.Document
import com.intellij.openapi.editor.RangeMarker
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.fileEditor.FileEditorLocation
import com.intellij.openapi.fileEditor.FileEditorState
import com.intellij.openapi.fileEditor.FileEditorStateLevel
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.vfs.VirtualFile
import org.jetbrains.annotations.Unmodifiable
import java.awt.BorderLayout
import javax.swing.JComponent
import javax.swing.JPanel

/**
 * Text-editor half of the proofread-page split editor. The document stays
 * the file's single serialized buffer
 * (`<noinclude><pagequality …/>header</noinclude>body<noinclude>footer</noinclude>`)
 * shown verbatim in a plain text editor — no header/body/footer field split.
 * The header and footer `<noinclude>` sections (tags included) are protected
 * with [Document.createGuardedBlock] so a proofreader's edits stay confined
 * to the body without the framing being editable or removable by accident.
 * See [ProofreadPageParts.boundaries] for the shape being guarded; a buffer
 * that doesn't parse into that shape (empty, malformed, legacy V1) is left
 * fully editable, matching that method's own fallback.
 */
class PrpTextEditor(
    private val delegate: TextEditor,
) : TextEditor by delegate {

    private val document: Document = delegate.editor.document

    private var headerGuard: RangeMarker? = null
    private var footerGuard: RangeMarker? = null

    /**
     * The editor whose text box↔text anchor offsets are relative to — see
     * [bodyStartOffset] for how those offsets map onto this whole-buffer
     * document.
     */
    val bodyEditor
        get() = delegate.editor

    /**
     * Offset in [bodyEditor]'s document where the editable body begins — the
     * end of the guarded header, or `0` when the buffer isn't structured
     * into header/body/footer (the whole buffer is then "body").
     */
    val bodyStartOffset: Int
        get() = headerGuard?.takeIf { it.isValid }?.endOffset ?: 0

    private val wrapper = JPanel(BorderLayout())

    init {
        val toolbar = WtPageNavToolbar(delegate.component, delegate.file)
        wrapper.add(toolbar.component, BorderLayout.NORTH)
        wrapper.add(delegate.component, BorderLayout.CENTER)

        updateGuards()
        document.addDocumentListener(object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) = updateGuards()
        }, this)
    }

    /** Re-derive the guarded header/footer ranges after any document change. */
    private fun updateGuards() {
        headerGuard?.let { if (it.isValid) document.removeGuardedBlock(it) }
        footerGuard?.let { if (it.isValid) document.removeGuardedBlock(it) }
        headerGuard = null
        footerGuard = null

        val bounds = ProofreadPageParts.boundaries(document.text) ?: return
        headerGuard = document.createGuardedBlock(bounds.header.first, bounds.header.last + 1).apply {
            isGreedyToRight = false
        }
        footerGuard = document.createGuardedBlock(bounds.footer.first, bounds.footer.last + 1).apply {
            isGreedyToLeft = false
        }
    }

    override fun getComponent(): JComponent = wrapper

    override fun getPreferredFocusedComponent(): JComponent =
        delegate.preferredFocusedComponent ?: delegate.editor.contentComponent

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
        headerGuard?.let { if (it.isValid) document.removeGuardedBlock(it) }
        footerGuard?.let { if (it.isValid) document.removeGuardedBlock(it) }
        Disposer.dispose(delegate)
    }

    override fun isEditorLoaded(): Boolean {
        return delegate.isEditorLoaded()
    }
}
