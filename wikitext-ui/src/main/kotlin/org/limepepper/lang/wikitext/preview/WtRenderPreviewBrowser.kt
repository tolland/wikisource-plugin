package org.limepepper.lang.wikitext.preview

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
 * Preview half of the wikitext split editor: a [FileEditor] shell that hosts
 * the [WtPreviewToolbar] and switches between two independently owned panes —
 *
 *  - [WtRenderPreviewPane]: the wiki-rendered HTML of the current document,
 *  - [WtReferenceImagePane]: the page's reference scan (proofread profile).
 *
 * Each pane keeps its own browser, so toggling between them is a pure card
 * switch: the scan is fetched once and its zoom/scroll state survives the
 * toggle, and document edits never reload the scan.
 */
class WtRenderPreviewBrowser(
    private val file: VirtualFile,
    /** Drives which toolbar actions the pane offers (reference image, …). */
    val profile: WtEditorProfile = WtEditorProfile.WIKITEXT,
) : UserDataHolderBase(), FileEditor, Disposable {
    private val component = JBPanel<JBPanel<*>>(BorderLayout())

    private val renderPane = WtRenderPreviewPane(file).also {
        Disposer.register(this, it)
    }

    private val imagePane: WtReferenceImagePane? =
        if (profile.hasReferenceImage) {
            WtReferenceImagePane(file).also { Disposer.register(this, it) }
        } else {
            null
        }

    /** The scan pane, for profiles that have one — box↔text linking wires into it. */
    val referenceImagePane: WtReferenceImagePane?
        get() = imagePane

    private val cards = CardLayout()
    private val cardPanel = JBPanel<JBPanel<*>>(cards).apply {
        add(renderPane.component, CARD_RENDER)
        imagePane?.let { add(it.component, CARD_IMAGE) }
    }

    @Volatile
    private var disposed = false

    /**
     * Proofread workflow: flips the pane between the rendered preview and the
     * page's reference scan. Set from the toggle in [WtPreviewToolbar]; only
     * profiles with a reference image (proofread-page) can turn it on.
     */
    var showReferenceImage: Boolean = false
        set(value) {
            if (value && imagePane == null) {
                return
            }
            if (field != value) {
                field = value
                if (value) {
                    imagePane?.ensureLoaded()
                }
                renderPane.visible = !value
                cards.show(cardPanel, if (value) CARD_IMAGE else CARD_RENDER)
            }
        }

    fun zoomImage(factor: Double) {
        imagePane?.zoomBy(factor)
    }

    fun resetImageZoom() {
        imagePane?.resetZoom()
    }

    /** The drag-selected OCR region of the scan, in image pixel coordinates. */
    fun referenceSelection(): Rectangle? = imagePane?.selection

    init {
        component.add(WtPreviewToolbar(this).component, BorderLayout.NORTH)
        component.add(cardPanel, BorderLayout.CENTER)
        reloadPreview()

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
        if (showReferenceImage && imagePane != null) imagePane.component else renderPane.component

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
