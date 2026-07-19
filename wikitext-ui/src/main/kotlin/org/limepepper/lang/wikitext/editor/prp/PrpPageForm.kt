package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.application.runReadActionBlocking
import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.editor.Document
import com.intellij.openapi.editor.EditorFactory
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.editor.ex.EditorEx
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.ComboBox
import com.intellij.testFramework.LightVirtualFile
import com.intellij.ui.JBColor
import com.intellij.ui.OnePixelSplitter
import com.intellij.ui.components.JBLabel
import com.intellij.ui.dsl.listCellRenderer.textListCellRenderer
import com.intellij.util.ui.JBUI
import org.limepepper.lang.wikitext.WtFileType
import java.awt.BorderLayout
import java.awt.FlowLayout
import java.awt.Font
import javax.swing.JComponent
import javax.swing.JPanel

/**
 * The header / body / footer editing surface for a `proofread-page`, the
 * three-field equivalent of MediaWiki's ProofreadPage edit form
 * (`wpHeaderTextbox` / `wpTextbox1` / `wpFooterTextbox` plus the page-quality
 * radio group, shown here as a level combo next to the header field).
 *
 * The canonical document stays the file's single serialized buffer
 * (`<noinclude><pagequality …/>header</noinclude>body<noinclude>footer</noinclude>`)
 * so save, PSI, and the preview keep working unchanged; this form is a *view*
 * over it. Each section is backed by its own [LightVirtualFile] with
 * [WtFileType] — a real (light) PSI file, so the fields get the full
 * lexer-highlighter *and* annotator stack, not just a bare document. The
 * fields are kept in sync with the file document in both directions:
 *
 *  - file → fields: on any change to the file buffer (external edit, undo,
 *    reload, raw-mode typing) the buffer is [ProofreadPageParts.decompose]d
 *    and the fields (and the quality combo) are refreshed.
 *  - fields → file: on any change to a field or the quality level the parts
 *    are [ProofreadPageParts.compose]d back into the file buffer.
 *
 * A [syncing] guard breaks the feedback loop so a write in one direction never
 * bounces back and resets carets. When the buffer is not in a recognised,
 * round-trippable layout (empty, malformed, or the legacy `<div>` V1 format —
 * see [ProofreadPageParts.decompose]) the form drops to a single raw field
 * bound verbatim to the buffer, so no page is ever corrupted.
 *
 * An alternative single-editor implementation — one document with the
 * `<noinclude>` framing folded away behind inlays and protected by guarded
 * regions instead of split fields — is planned; this class is where the two
 * variants would share their sync logic.
 */
class PrpPageForm(
    private val project: Project,
    textEditor: TextEditor,
) : Disposable {
    private val fileDocument: Document = textEditor.editor.document

    private val editorFactory = EditorFactory.getInstance()

    private val headerEditor = createSectionEditor("proofread-header.wt")
    private val bodyEditor = createSectionEditor("proofread-body.wt")
    private val footerEditor = createSectionEditor("proofread-footer.wt")

    /** Guards against the sync feedback loop (see the class doc). */
    private var syncing = false

    /**
     * The `<pagequality/>` tag of the current page, kept out of the header
     * field (like the web editor's radio group). Level is user-editable via
     * [qualityCombo]; the user attribution is carried through unchanged.
     */
    private var quality: PageQuality? = null

    private val qualityCombo = ComboBox(PageQuality.LEVELS.toList().toTypedArray()).apply {
        renderer = textListCellRenderer<Int> { "$it — ${PageQuality.levelName(it)}" }
        addActionListener { if (!syncing) qualityLevelPicked() }
    }

    private val qualityUserLabel = JBLabel().apply {
        foreground = JBColor.GRAY
    }

    private val qualityRow: JComponent = JPanel(FlowLayout(FlowLayout.LEFT, JBUI.scale(6), 0)).apply {
        isOpaque = false
        add(JBLabel("Page quality:"))
        add(qualityCombo)
        add(qualityUserLabel)
    }

    private val headerSection = section("Header", headerEditor, qualityRow)
    private val footerSection = section("Footer", footerEditor)

    private val bodyFooterSplitter = OnePixelSplitter(true, BODY_FOOTER_SPLIT)
    private val rootSplitter = OnePixelSplitter(true, HEADER_SPLIT)

    /**
     * Whether the buffer parsed into header/body/footer. `false` means raw
     * mode: only [bodyEditor] is shown and it holds the whole buffer verbatim.
     */
    private var structured = true

    val component: JComponent = JPanel(BorderLayout())

    val preferredFocusComponent: JComponent
        get() = bodyEditor.contentComponent

    /**
     * The body (transcription) section editor — the anchor chrome of
     * box↔text linking renders here, and anchor offsets are offsets into
     * this document (for an unstructured buffer it holds the whole file).
     */
    val bodySectionEditor: EditorEx
        get() = bodyEditor

    init {
        bodyFooterSplitter.firstComponent = section("Body", bodyEditor)
        bodyFooterSplitter.secondComponent = footerSection
        rootSplitter.firstComponent = headerSection
        rootSplitter.secondComponent = bodyFooterSplitter

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
        quality = parts?.header?.quality
        withSync {
            ApplicationManager.getApplication().runWriteAction {
                if (parts != null) {
                    setSection(headerEditor.document, parts.header.text)
                    setSection(bodyEditor.document, parts.body)
                    setSection(footerEditor.document, parts.footer)
                } else {
                    setSection(headerEditor.document, "")
                    setSection(bodyEditor.document, fileDocument.text)
                    setSection(footerEditor.document, "")
                }
            }
            quality?.let {
                qualityCombo.selectedItem = it.level
                qualityUserLabel.text = "user: ${it.user}"
            }
        }
        // In raw mode only the body field is shown; collapse the header/footer
        // panes so they leave no gap in the splitters. The quality row also
        // hides when the header carries no pagequality tag.
        qualityRow.isVisible = structured && quality != null
        headerSection.isVisible = structured
        footerSection.isVisible = structured
        rootSplitter.proportion = if (structured) HEADER_SPLIT else 0f
        bodyFooterSplitter.proportion = if (structured) BODY_FOOTER_SPLIT else 1f
    }

    private fun qualityLevelPicked() {
        val current = quality ?: return
        val level = qualityCombo.selectedItem as? Int ?: return
        if (level == current.level) return
        quality = current.copy(level = level)
        writeToFile()
    }

    /** Reassemble the parts and push the result into the file buffer. */
    private fun writeToFile() {
        val newText = if (structured) {
            ProofreadPageParts(
                header = ProofreadPageHeader(quality, headerEditor.document.text),
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

    /**
     * Each section is a real editor over a [LightVirtualFile] with
     * [WtFileType], so the document has a PSI file behind it and the daemon
     * runs the full highlighting stack (lexer highlighter + annotator) —
     * a plain [EditorFactory.createDocument] document gets neither.
     */
    private fun createSectionEditor(name: String): EditorEx {
        val file = LightVirtualFile(name, WtFileType, "")
        val document = runReadActionBlocking {
            FileDocumentManager.getInstance().getDocument(file)
        } ?: editorFactory.createDocument("")
        val editor = editorFactory.createEditor(document, project, file, false) as EditorEx
        editor.settings.apply {
            isLineNumbersShown = true
            isLineMarkerAreaShown = true
            isFoldingOutlineShown = true
            additionalColumnsCount = 0
            isUseSoftWraps = true
        }
        return editor
    }

    private fun section(title: String, editor: EditorEx, titleTrailer: JComponent? = null): JComponent {
        val label = JBLabel(title).apply {
            border = JBUI.Borders.empty(3, 6)
            font = font.deriveFont(Font.BOLD, font.size - 1f)
            foreground = JBColor.GRAY
        }
        val north: JComponent = if (titleTrailer == null) {
            label
        } else {
            JPanel(BorderLayout()).apply {
                isOpaque = false
                add(label, BorderLayout.WEST)
                add(titleTrailer, BorderLayout.CENTER)
            }
        }
        return JPanel(BorderLayout()).apply {
            add(north, BorderLayout.NORTH)
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
