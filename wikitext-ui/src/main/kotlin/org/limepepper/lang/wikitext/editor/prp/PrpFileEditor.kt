package org.limepepper.lang.wikitext.editor.prp

import com.intellij.ide.impl.StructureViewWrapperImpl
import com.intellij.ide.structureView.StructureViewBuilder
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.TextEditorWithPreview
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.vfs.VirtualFile
import org.limepepper.lang.wikitext.annotation.BoundingBox
import java.awt.Component
import java.awt.KeyboardFocusManager
import java.beans.PropertyChangeListener
import javax.swing.SwingUtilities

/**
 * Provides an implementation of FileEditor, suitable for use by [PrpFileEditorProvider] via its' [com.intellij.openapi.fileEditor.FileEditorProvider.createEditor] method.
 */
class PrpFileEditor private constructor(
    private val editorHalf: PrpTextEditor,
    private val previewHalf: PrpPreviewBrowser,
) : TextEditorWithPreview(editorHalf, previewHalf) {
    constructor(project: Project, editor: TextEditor, file: VirtualFile) :
        this(PrpTextEditor(editor), PrpPreviewBrowser(file))

    /** Which pane's structure the Structure tool window should reflect. */
    enum class ActivePane { EDITOR, PREVIEW_RENDER, PREVIEW_IMAGE }

    // In SHOW_EDITOR_AND_PREVIEW both panes are visible, so "active" is decided
    // by focus; the split layouts pin it. Updated by [focusListener].
    private var previewFocused = false

    // Fires whenever focus crosses between the two panes so the structure view,
    // which differs per pane, can be refreshed.
    private val focusListener = PropertyChangeListener { event ->
        val owner = event.newValue as? Component ?: return@PropertyChangeListener
        val inPreview = SwingUtilities.isDescendingFrom(owner, previewHalf.component)
        val inEditor = SwingUtilities.isDescendingFrom(owner, editorHalf.component)
        if ((inPreview || inEditor) && inPreview != previewFocused) {
            previewFocused = inPreview
            refreshStructureView()
        }
    }

    init {
        // Initialize TextEditorWithPreview's lazy UI before disposal-sensitive editor switching can occur.
        component

        // Box↔text linking: the anchor manager renders text anchors in the
        // body editor and owns the canvas's right-click link actions (the
        // scan itself loads eagerly in PrpPreviewBrowser's init). Anchor
        // offsets are body-relative (see WtAnnotationAnchorManager), so they
        // need translating against the guarded header's end offset in the
        // editor's whole-buffer document.
        val pane = previewHalf.referenceImagePane
        val anchorManager = WtAnnotationAnchorManager(
            editorHalf.bodyEditor,
            pane.model,
            bodyStartOffset = { editorHalf.bodyStartOffset },
            revidSupplier = { pane.baseRevid },
            onRevealBox = { boxId ->
                previewHalf.showReferenceImage = true
                pane.revealBox(boxId)
            },
        )
        Disposer.register(this, anchorManager)
        pane.installPopupMenu(anchorManager::createPopupMenu)

        // Toggling the preview card (scan ↔ rendered HTML) changes which
        // structure applies, as does moving focus between the panes.
        previewHalf.onPaneChanged = ::refreshStructureView
        KeyboardFocusManager.getCurrentKeyboardFocusManager()
            .addPropertyChangeListener("focusOwner", focusListener)
        Disposer.register(this) {
            KeyboardFocusManager.getCurrentKeyboardFocusManager()
                .removePropertyChangeListener("focusOwner", focusListener)
        }
    }

    /** The pane whose structure the tool window should currently show. */
    fun activePane(): ActivePane {
        val previewActive = when (getLayout()) {
            Layout.SHOW_PREVIEW -> true
            Layout.SHOW_EDITOR -> false
            else -> previewFocused
        }
        return when {
            !previewActive -> ActivePane.EDITOR
            previewHalf.showReferenceImage -> ActivePane.PREVIEW_IMAGE
            else -> ActivePane.PREVIEW_RENDER
        }
    }

    override fun getStructureViewBuilder(): StructureViewBuilder =
        PrpStructureViewBuilder(editorHalf, previewHalf, ::activePane, ::navigateToBox)

    override fun onLayoutChange(oldValue: Layout?, newValue: Layout?) {
        super.onLayoutChange(oldValue, newValue)
        refreshStructureView()
    }

    /**
     * Reveals [box] on the scan and, when it carries a text anchor, jumps the
     * transcription caret to the linked region — the same mapping the anchor
     * chrome uses (offsets are body-relative, see [PrpTextEditor.bodyStartOffset]).
     */
    private fun navigateToBox(box: BoundingBox) {
        previewHalf.showReferenceImage = true
        previewHalf.referenceImagePane.revealBox(box.id)

        val textStart = box.textStart ?: return
        val editor = editorHalf.bodyEditor
        val offset = (editorHalf.bodyStartOffset + textStart)
            .coerceIn(0, editor.document.textLength)
        editor.caretModel.moveToOffset(offset)
        editor.scrollingModel.scrollToCaret(com.intellij.openapi.editor.ScrollType.MAKE_VISIBLE)
    }

    /**
     * Asks the Structure tool window to re-query [getStructureViewBuilder]. The
     * window only rebuilds on file/selection changes on its own, and switching
     * panes here changes neither, so nudge it explicitly. Same broadcast the
     * bundled JSON/YAML/XML structure factories use.
     */
    private fun refreshStructureView() {
        ApplicationManager.getApplication().messageBus
            .syncPublisher(StructureViewWrapperImpl.STRUCTURE_CHANGED)
            .run()
    }
}
