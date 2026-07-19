package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.runReadActionBlocking
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditor
import com.intellij.openapi.fileEditor.FileEditorState
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.util.UserDataHolderBase
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.ui.components.JBPanel
import java.awt.BorderLayout
import java.awt.CardLayout
import java.awt.Rectangle
import java.beans.PropertyChangeListener
import javax.swing.JComponent

/**
 * this is provided to the right pane of TextEditorWithPreview
 * it is an implementation of FileEditor
 * we are using Panels to swap between the reference-image
 * and the preview render from the wiki backend
 */
class PrpPreviewBrowser(
    private val file: VirtualFile,
) : UserDataHolderBase(), FileEditor, Disposable {

    private val component = JBPanel<JBPanel<*>>(BorderLayout())

    private val renderPane = RenderPreviewPane(file).also {
        Disposer.register(this, it)
    }

    private val imagePane =
        ReferenceImagePane(file).also { Disposer.register(this, it) }


    /** The scan pane, for profiles that have one — box↔text linking wires into it. */
    val referenceImagePane: ReferenceImagePane
        get() = imagePane

    private val cards = CardLayout()
    private val cardPanel = JBPanel<JBPanel<*>>(cards).apply {
        add(imagePane.component, CARD_IMAGE)
        add(renderPane.component, CARD_RENDER)
    }

    @Volatile
    private var disposed = false

    /**
     * Proofread workflow: flips the pane between the rendered preview and the
     * page's reference scan. Set from the toggle in [PrpPreviewToolbar]; only
     * profiles with a reference image (proofread-page) can turn it on.
     */
    var showReferenceImage: Boolean = true
        set(value) {
            if (field != value) {
                field = value
                if (value) {
                    imagePane.ensureLoaded()
                }
                renderPane.visible = !value
                cards.show(cardPanel, if (value) CARD_IMAGE else CARD_RENDER)
            }
        }

    fun zoomImage(factor: Double) {
        imagePane.zoomBy(factor)
    }

    fun resetImageZoom() {
        imagePane.resetZoom()
    }

    /** The drag-selected OCR region of the scan, in image pixel coordinates. */
    fun referenceSelection(): Rectangle? = imagePane.selection

    init {
        component.add(PrpPreviewToolbar(this).component, BorderLayout.NORTH)
        component.add(cardPanel, BorderLayout.CENTER)
        // The reference image is the initial card (wikisource editor
        // convention), but the showReferenceImage setter's no-change guard
        // never fires for the field's initial value — apply that state here.
        imagePane.ensureLoaded()
        cards.show(cardPanel, CARD_IMAGE)
        // The render pane starts hidden; scheduleReload() just marks it
        // pending, so the first toggle to the render card triggers the reload.
        renderPane.scheduleReload()

        runReadActionBlocking {
            FileDocumentManager.getInstance().getDocument(file)?.addDocumentListener(object : DocumentListener {
                override fun documentChanged(event: DocumentEvent) {
                    renderPane.scheduleReload()
                }
            }, this)
        }
    }

    fun reloadPreview() {
        if (!disposed) {
            renderPane.reload()
        }
    }

    override fun getComponent(): JComponent = component

    override fun getPreferredFocusedComponent(): JComponent =
        if (showReferenceImage) imagePane.component else renderPane.component

    override fun getName(): String = "Wikitext Preview"

    override fun setState(state: FileEditorState) = Unit

    override fun isModified(): Boolean = false

    override fun isValid(): Boolean = !disposed && file.isValid

    override fun addPropertyChangeListener(listener: PropertyChangeListener) = Unit

    override fun removePropertyChangeListener(listener: PropertyChangeListener) = Unit

    override fun getFile(): VirtualFile = file

    override fun dispose() {
        disposed = true
    }

    private companion object {
        const val CARD_RENDER = "render"
        const val CARD_IMAGE = "reference-image"
    }
}
