package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.editor.Document
import com.intellij.openapi.editor.EditorFactory
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.editor.ex.EditorEx
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.project.Project
import com.intellij.ui.JBColor
import com.intellij.ui.OnePixelSplitter
import com.intellij.ui.components.JBLabel
import com.intellij.util.ui.JBUI
import org.limepepper.lang.wikitext.WtFileType
import java.awt.BorderLayout
import java.awt.Font
import javax.swing.JComponent
import javax.swing.JPanel

/**
 * The header / body / footer editing surface for a `proofread-page`, the
 * three-field equivalent of MediaWiki's ProofreadPage edit form
 * (`wpHeaderTextbox` / `wpTextbox1` / `wpFooterTextbox`).
 *
 * The canonical document stays the file's single serialized buffer
 * (`<noinclude>header</noinclude>body<noinclude>footer</noinclude>`) so save,
 * PSI, and the preview keep working unchanged; this form is a *view* over it.
 * Three in-memory editor documents mirror the sections and are kept in sync
 * with the file document in both directions:
 *
 *  - file → fields: on any change to the file buffer (external edit, undo,
 *    reload) the buffer is [ProofreadPageParts.decompose]d and the fields are
 *    refreshed.
 *  - fields → file: on any change to a field the three are
 *    [ProofreadPageParts.compose]d back into the file buffer.
 *
 * A [syncing] guard breaks the feedback loop so a write in one direction never
 * bounces back and resets carets. When the buffer is not in a recognised,
 * round-trippable layout (empty, malformed, or the legacy `<div>` V1 format —
 * see [ProofreadPageParts.decompose]) the form drops to a single raw field
 * bound verbatim to the buffer, so no page is ever corrupted.
 */
class WtProofreadPageForm(
    private val project: Project,
    textEditor: TextEditor,
) : Disposable {
    private val fileDocument: Document = textEditor.editor.document

    private val editorFactory = EditorFactory.getInstance()

    private val headerEditor = createSectionEditor()
    private val bodyEditor = createSectionEditor()
    private val footerEditor = createSectionEditor()

    private val headerSection = section("Header", headerEditor)
    private val footerSection = section("Footer", footerEditor)

    private val bodyFooterSplitter = OnePixelSplitter(true, BODY_FOOTER_SPLIT)
    private val rootSplitter = OnePixelSplitter(true, HEADER_SPLIT)

    /** Guards against the sync feedback loop (see the class doc). */
    private var syncing = false

    /**
     * Whether the buffer parsed into header/body/footer. `false` means raw
     * mode: only [bodyEditor] is shown and it holds the whole buffer verbatim.
     */
    private var structured = true

    val component: JComponent = JPanel(BorderLayout())

    val preferredFocusComponent: JComponent
        get() = bodyEditor.contentComponent

    init {
        bodyFooterSplitter.firstComponent = section("Body", bodyEditor)
        bodyFooterSplitter.secondComponent = footerSection
        rootSplitter.firstComponent = headerSection
        rootSplitter.secondComponent = bodyFooterSplitter

        component.add(WtPageNavToolbar(bodyEditor.component, textEditor.file).component, BorderLayout.NORTH)
        component.add(rootSplitter, BorderLayout.CENTER)

        loadFromFile()

        val fileListener = object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) {
                if (!syncing) loadFromFile()
            }
        }
        fileDocument.addDocumentListener(fileListener, this)

        val fieldListener = object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) {
                if (!syncing) writeToFile()
            }
        }
        headerEditor.document.addDocumentListener(fieldListener, this)
        bodyEditor.document.addDocumentListener(fieldListener, this)
        footerEditor.document.addDocumentListener(fieldListener, this)
    }

    /** Pull the file buffer apart and refresh the three fields. */
    private fun loadFromFile() {
        val parts = ProofreadPageParts.decompose(fileDocument.text)
        structured = parts != null
        withSync {
            ApplicationManager.getApplication().runWriteAction {
                if (parts != null) {
                    setSection(headerEditor.document, parts.header)
                    setSection(bodyEditor.document, parts.body)
                    setSection(footerEditor.document, parts.footer)
                } else {
                    setSection(headerEditor.document, "")
                    setSection(bodyEditor.document, fileDocument.text)
                    setSection(footerEditor.document, "")
                }
            }
        }
        // In raw mode only the body field is shown; collapse the header/footer
        // panes so they leave no gap in the splitters.
        headerSection.isVisible = structured
        footerSection.isVisible = structured
        rootSplitter.proportion = if (structured) HEADER_SPLIT else 0f
        bodyFooterSplitter.proportion = if (structured) BODY_FOOTER_SPLIT else 1f
    }

    /** Reassemble the three fields and push the result into the file buffer. */
    private fun writeToFile() {
        val newText = if (structured) {
            ProofreadPageParts(
                header = headerEditor.document.text,
                body = bodyEditor.document.text,
                footer = footerEditor.document.text,
            ).compose()
        } else {
            bodyEditor.document.text
        }
        if (newText == fileDocument.text) return
        withSync {
            WriteCommandAction.writeCommandAction(project)
                .withName("Edit Proofread Page")
                .run<RuntimeException> { fileDocument.setText(newText) }
        }
    }

    private fun setSection(document: Document, text: String) {
        if (document.text != text) document.setText(text)
    }

    private inline fun withSync(block: () -> Unit) {
        syncing = true
        try {
            block()
        } finally {
            syncing = false
        }
    }

    private fun createSectionEditor(): EditorEx {
        val document = editorFactory.createDocument("")
        val editor = editorFactory.createEditor(document, project, WtFileType, false) as EditorEx
        editor.settings.apply {
            isLineNumbersShown = false
            isLineMarkerAreaShown = false
            isFoldingOutlineShown = false
            additionalColumnsCount = 0
            isUseSoftWraps = true
        }
        return editor
    }

    private fun section(title: String, editor: EditorEx): JComponent {
        val label = JBLabel(title).apply {
            border = JBUI.Borders.empty(3, 6)
            font = font.deriveFont(Font.BOLD, font.size - 1f)
            foreground = JBColor.GRAY
        }
        return JPanel(BorderLayout()).apply {
            add(label, BorderLayout.NORTH)
            add(editor.component, BorderLayout.CENTER)
        }
    }

    override fun dispose() {
        editorFactory.releaseEditor(headerEditor)
        editorFactory.releaseEditor(bodyEditor)
        editorFactory.releaseEditor(footerEditor)
    }

    private companion object {
        /** Fraction of the height given to the header pane above the body/footer. */
        const val HEADER_SPLIT = 0.16f

        /** Fraction of the body/footer sub-area given to the body above the footer. */
        const val BODY_FOOTER_SPLIT = 0.82f
    }
}
