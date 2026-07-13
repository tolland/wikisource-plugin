package org.limepepper.lang.wikitext.preview

import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.ToggleAction
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.vfs.VirtualFile
import java.awt.BorderLayout
import java.awt.CardLayout
import javax.swing.JComponent
import javax.swing.JPanel

/**
 * Editor for `proofread-page` bodies (transcriptions). The editor half is not
 * the raw serialized buffer but a [WtProofreadPageForm] — separate header,
 * body, and footer fields plus the page-quality control, the desktop
 * equivalent of the wiki's ProofreadPage edit form. The form keeps the file's
 * single `<noinclude><pagequality …/>header</noinclude>body<noinclude>footer</noinclude>`
 * buffer as the source of truth (so save, PSI, and the preview are unaffected)
 * and edits it through [ProofreadPageParts]; the underlying [TextEditor] stays
 * live to back the document, state, and navigation machinery, and can be
 * brought on screen with the raw-mode toggle in the toolbar.
 */
class WtProofreadPageEditor private constructor(
    editorHalf: WtProofreadFormTextEditor,
    previewEditor: WtRenderPreviewBrowser,
) : WtEditorWithPreview(
    editorHalf,
    previewEditor,
    "Proofread Page Editor",
    WtEditorProfile.PROOFREAD_PAGE,
) {
    constructor(project: Project, textEditor: TextEditor, previewEditor: WtRenderPreviewBrowser) :
        this(WtProofreadFormTextEditor(project, textEditor), previewEditor)

    init {
        // Box↔text linking: the anchor manager renders text anchors in the
        // form's body editor and owns the canvas's right-click link actions;
        // the scan (and its boxes) loads eagerly so anchors appear without
        // first opening the reference-image card.
        previewEditor.referenceImagePane?.let { pane ->
            val anchorManager = WtAnnotationAnchorManager(
                editorHalf.bodyEditor,
                pane.model,
                revidSupplier = { pane.baseRevid },
                onRevealBox = { boxId ->
                    previewEditor.showReferenceImage = true
                    pane.revealBox(boxId)
                },
            )
            Disposer.register(this, anchorManager)
            pane.installPopupMenu(anchorManager::createPopupMenu)
            pane.ensureLoaded()
        }
    }
}
