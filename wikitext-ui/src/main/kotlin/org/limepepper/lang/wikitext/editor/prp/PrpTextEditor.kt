package org.limepepper.lang.wikitext.editor.prp

import com.intellij.codeHighlighting.BackgroundEditorHighlighter
import com.intellij.ide.structureView.StructureViewBuilder
import com.intellij.openapi.actionSystem.ActionGroup
import com.intellij.openapi.editor.Document
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.editor.Inlay
import com.intellij.openapi.editor.EditorCustomElementRenderer
import com.intellij.openapi.editor.RangeMarker
import com.intellij.openapi.editor.colors.EditorFontType
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.editor.markup.TextAttributes
import com.intellij.openapi.fileEditor.FileEditorLocation
import com.intellij.openapi.fileEditor.FileEditorState
import com.intellij.openapi.fileEditor.FileEditorStateLevel
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.util.UserDataHolderBase
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.pom.Navigatable
import com.intellij.ui.JBColor
import org.jetbrains.annotations.Unmodifiable
import java.awt.BorderLayout
import java.awt.Font
import java.awt.Graphics
import java.awt.Graphics2D
import java.awt.Rectangle
import java.awt.RenderingHints
import java.beans.PropertyChangeListener
import javax.swing.JComponent
import javax.swing.JPanel

/**
 * Text-editor half of the proofread-page split editor. The document stays
 * the file's single serialized buffer
 * (`<noinclude><pagequality …/>header</noinclude>body<noinclude>footer</noinclude>`)
 * shown verbatim in a plain text editor — no header/body/footer field split.
 *
 * Only the `<noinclude>`/`<pagequality …/>` *tags* themselves are protected
 * with [Document.createGuardedBlock] (see [ProofreadPageParts.tagSpans]) — a
 * proofreader can still edit the running-header and footer wikitext that sits
 * between the tags, just not remove or corrupt the framing. A divider block
 * inlay marks the top of the header and the header/body and body/footer
 * seams, which also stands in for the implicit line break the web editor
 * shows there without it actually being a `\n` in the buffer (and, for the
 * body/footer seam, the blank line the web editor always shows above the
 * footer box despite trimming the matching trailing newline from what's
 * actually stored — force a real blank line to survive with `{{nop}}`, same
 * as the web UI). A buffer that doesn't parse into header/body/footer shape
 * (empty, malformed, legacy V1) is left fully editable and undecorated,
 * matching [ProofreadPageParts.tagSpans]'s own fallback.
 */
class PrpTextEditor(
    private val delegate: TextEditor,
) : UserDataHolderBase(), TextEditor {

    private val document: Document = delegate.editor.document

    private var guards: List<RangeMarker> = emptyList()
    private var dividers: List<Inlay<*>> = emptyList()

    /**
     * The editor whose text box↔text anchor offsets are relative to — see
     * [bodyStartOffset] for how those offsets map onto this whole-buffer
     * document.
     */
    val bodyEditor: Editor
        get() = delegate.editor

    /**
     * Offset in [bodyEditor]'s document where the editable body begins — the
     * end of the guarded header close tag, or `0` when the buffer isn't
     * structured into header/body/footer (the whole buffer is then "body").
     */
    var bodyStartOffset: Int = 0
        private set

    /**
     * Offset in [bodyEditor]'s document where the editable body ends — the
     * start of the guarded footer open tag, or the document length when the
     * buffer isn't structured into header/body/footer.
     */
    var bodyEndOffset: Int = 0
        private set

    private val wrapper = JPanel(BorderLayout())

    init {
        val toolbar = WtPageNavToolbar(delegate.component, delegate.file)
        wrapper.add(toolbar.component, BorderLayout.NORTH)
        wrapper.add(delegate.component, BorderLayout.CENTER)

        updateDecorations()
        document.addDocumentListener(object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) = updateDecorations()
        }, this)
    }

    /** Re-derive the guarded tag ranges and divider inlays after any document change. */
    private fun updateDecorations() {
        guards.forEach { if (it.isValid) document.removeGuardedBlock(it) }
        guards = emptyList()
        dividers.forEach { Disposer.dispose(it) }
        dividers = emptyList()
        bodyStartOffset = 0
        bodyEndOffset = document.textLength

        val spans = ProofreadPageParts.tagSpans(document.text) ?: return

        guards = listOf(spans.headerOpen, spans.headerClose, spans.footerOpen, spans.footerClose).map { span ->
            document.createGuardedBlock(span.first, span.last + 1).apply {
                isGreedyToLeft = false
                isGreedyToRight = false
            }
        }
        bodyStartOffset = spans.headerClose.last + 1
        bodyEndOffset = spans.footerOpen.first

        val editor = delegate.editor
        dividers = listOfNotNull(
            addDivider(
                editor,
                spans.headerOpen.first,
                "Header",
            ),
            addDivider(
                editor,
                bodyStartOffset,
                "Body",
            ),
            addDivider(
                editor,
                spans.footerOpen.first,
                "Footer",
            ),
        )
    }

    private fun addDivider(
        editor: Editor,
        offset: Int,
        label: String,
    ): Inlay<*>? =
        editor.inlayModel.addBlockElement(
            offset,
            false,
            true,
            0,
            SectionDividerRenderer(label),
        )

    override fun getComponent(): JComponent = wrapper

    override fun getPreferredFocusedComponent(): JComponent =
        delegate.preferredFocusedComponent ?: delegate.editor.contentComponent

    override fun getEditor(): Editor = delegate.editor

    override fun getName(): String = delegate.name

    override fun isModified(): Boolean = delegate.isModified

    override fun isValid(): Boolean = delegate.isValid

    override fun addPropertyChangeListener(listener: PropertyChangeListener) {
        delegate.addPropertyChangeListener(listener)
    }

    override fun removePropertyChangeListener(listener: PropertyChangeListener) {
        delegate.removePropertyChangeListener(listener)
    }

    override fun canNavigateTo(navigatable: Navigatable): Boolean = delegate.canNavigateTo(navigatable)

    override fun navigateTo(navigatable: Navigatable) {
        delegate.navigateTo(navigatable)
    }

    override fun getState(level: FileEditorStateLevel): FileEditorState {
        return delegate.getState(level)
    }

    override fun setState(state: FileEditorState) {
        delegate.setState(state)
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

    // The platform's deprecated default getFile() (which logs a PluginException)
    // would otherwise be in effect here — a @NotNull override is required.
    override fun getFile(): VirtualFile = delegate.file
    override fun getFilesToRefresh(): @Unmodifiable List<VirtualFile> {
        return delegate.filesToRefresh
    }

    override fun getTabActions(): ActionGroup? {
        return delegate.tabActions
    }

    override fun dispose() {
        guards.forEach { if (it.isValid) document.removeGuardedBlock(it) }
        dividers.forEach { Disposer.dispose(it) }
        Disposer.dispose(delegate)
    }

    // TextEditor.isEditorLoaded() is an @ApiStatus.Internal/@Experimental
    // default method — deliberately not overridden (the plugin verifier
    // flags both overriding it and invoking it as internal-API usage). The
    // interface's own default (`true`) applies here instead.

    /** A thin labeled rule marking a header/body/footer seam — see the class doc. */
    private class SectionDividerRenderer(private val label: String) : EditorCustomElementRenderer {
        override fun calcWidthInPixels(inlay: Inlay<*>): Int = 0

        override fun calcHeightInPixels(inlay: Inlay<*>): Int {
            val metrics = inlay.editor.contentComponent.getFontMetrics(labelFont(inlay))
            return metrics.height + 2 * PADDING_PX
        }

        override fun paint(inlay: Inlay<*>, g: Graphics, targetRegion: Rectangle, textAttributes: TextAttributes) {
            val g2 = g as Graphics2D
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            val font = labelFont(inlay)
            val metrics = inlay.editor.contentComponent.getFontMetrics(font)
            val midY = targetRegion.y + targetRegion.height / 2
            g2.color = JBColor.border()
            g2.drawLine(targetRegion.x, midY, targetRegion.x + targetRegion.width, midY)

            val labelX = targetRegion.x + LABEL_INSET_PX
            val labelWidth = metrics.stringWidth(label)
            g2.color = inlay.editor.contentComponent.background
            g2.fillRect(labelX - 2, targetRegion.y, labelWidth + 4, targetRegion.height)

            g2.color = JBColor.GRAY
            g2.font = font
            g2.drawString(label, labelX, targetRegion.y + metrics.ascent + (targetRegion.height - metrics.height) / 2)
        }

        private fun labelFont(inlay: Inlay<*>): Font {
            val editorFont = inlay.editor.colorsScheme.getFont(EditorFontType.PLAIN)
            return editorFont.deriveFont(Font.BOLD, editorFont.size2D - 2f)
        }

        private companion object {
            const val PADDING_PX = 4
            const val LABEL_INSET_PX = 8
        }
    }
}
