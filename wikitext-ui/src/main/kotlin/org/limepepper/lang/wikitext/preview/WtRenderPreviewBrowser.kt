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
import java.beans.PropertyChangeListener
import javax.swing.JComponent

/**
 * Preview half of the wikitext split editor: a [FileEditor] shell that hosts
 * the [WtPreviewToolbar] and a [WtRenderPreviewPane] showing the
 * wiki-rendered HTML of the current document.
 *
 * The reference-scan pane lives with the rest of the proofread-page
 * machinery in [org.limepepper.lang.wikitext.editor.prp.PrpPreviewBrowser].
 */
class WtRenderPreviewBrowser(
    private val file: VirtualFile,
) : UserDataHolderBase(), FileEditor, Disposable {
    private val component = JBPanel<JBPanel<*>>(BorderLayout())

    private val renderPane = WtRenderPreviewPane(file).also {
        Disposer.register(this, it)
    }

    @Volatile
    private var disposed = false

    init {
        component.add(WtPreviewToolbar(this).component, BorderLayout.NORTH)
        component.add(renderPane.component, BorderLayout.CENTER)
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

    override fun getPreferredFocusedComponent(): JComponent = renderPane.component

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
}
