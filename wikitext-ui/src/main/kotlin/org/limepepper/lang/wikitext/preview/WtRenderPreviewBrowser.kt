package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.Disposable
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditor
import com.intellij.openapi.fileEditor.FileEditorState
import com.intellij.openapi.util.UserDataHolderBase
import com.intellij.openapi.vfs.VfsUtilCore
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.ui.components.JBPanel
import com.intellij.ui.components.JBScrollPane
import com.intellij.ui.components.JBTextArea
import java.awt.BorderLayout
import java.beans.PropertyChangeListener
import javax.swing.JComponent
import javax.swing.Timer

class WtRenderPreviewBrowser(
    private val file: VirtualFile,
) : UserDataHolderBase(), FileEditor, Disposable {
    private val component = JBPanel<JBPanel<*>>(BorderLayout())
    private val previewText = JBTextArea().apply {
        isEditable = false
        lineWrap = true
        wrapStyleWord = true
        emptyText.text = "Wikitext preview is not implemented yet."
    }
    private val reloadTimer = Timer(250) { reloadPreview() }.apply {
        isRepeats = false
    }

    private var disposed = false

    init {
        component.add(JBScrollPane(previewText), BorderLayout.CENTER)
        reloadPreview()

        FileDocumentManager.getInstance().getDocument(file)?.addDocumentListener(object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) {
                scheduleReload()
            }
        }, this)
    }

    private fun scheduleReload() {
        if (!disposed) {
            reloadTimer.restart()
        }
    }

    fun reloadPreview() {
        if (disposed) {
            return
        }

        previewText.text = renderPreview(readWikitext())
        previewText.caretPosition = 0
    }

    private fun readWikitext(): String {
        val document = FileDocumentManager.getInstance().getDocument(file)
        return document?.text ?: VfsUtilCore.loadText(file)
    }

    private fun renderPreview(wikitext: String): String {
        val content = wikitext.trim()
        return if (content.isEmpty()) {
            "Wikitext preview is not implemented yet."
        } else {
            content
        }
    }

    override fun getComponent(): JComponent = component

    override fun getPreferredFocusedComponent(): JComponent = previewText

    override fun getName(): String = "Wikitext Preview"

    override fun setState(state: FileEditorState) = Unit

    override fun isModified(): Boolean = false

    override fun isValid(): Boolean = !disposed && file.isValid

    override fun addPropertyChangeListener(listener: PropertyChangeListener) = Unit

    override fun removePropertyChangeListener(listener: PropertyChangeListener) = Unit

    override fun getFile(): VirtualFile = file

    override fun dispose() {
        disposed = true
        reloadTimer.stop()
    }
}
