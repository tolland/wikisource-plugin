package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.TextEditorWithPreview
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.vfs.VirtualFile

/**
 * Provides an implementation of FileEditor, suitable for use by [PrpFileEditorProvider] via its' [com.intellij.openapi.fileEditor.FileEditorProvider.createEditor] method.
 */
class PrpFileEditor private constructor(
    private val editorHalf: PrpTextEditor,
    private val previewHalf: PrpPreviewBrowser,
) : TextEditorWithPreview(editorHalf, previewHalf) {
    constructor(project: Project, editor: TextEditor, file: VirtualFile) :
        this(PrpTextEditor(project, editor), PrpPreviewBrowser(file))

    init {
        // Initialize TextEditorWithPreview's lazy UI before disposal-sensitive editor switching can occur.
        component

        // Box↔text linking: the anchor manager renders text anchors in the
        // form's body editor and owns the canvas's right-click link actions
        // (the scan itself loads eagerly in PrpPreviewBrowser's init).
        val pane = previewHalf.referenceImagePane
        val anchorManager = WtAnnotationAnchorManager(
            editorHalf.bodyEditor,
            pane.model,
            revidSupplier = { pane.baseRevid },
            onRevealBox = { boxId ->
                previewHalf.showReferenceImage = true
                pane.revealBox(boxId)
            },
        )
        Disposer.register(this, anchorManager)
        pane.installPopupMenu(anchorManager::createPopupMenu)
    }
}
