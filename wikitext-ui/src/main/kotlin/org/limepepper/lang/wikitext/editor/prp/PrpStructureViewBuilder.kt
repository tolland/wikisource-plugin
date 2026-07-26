package org.limepepper.lang.wikitext.editor.prp

import com.intellij.ide.structureView.StructureView
import com.intellij.ide.structureView.StructureViewBuilder
import com.intellij.ide.structureView.newStructureView.StructureViewComponent
import com.intellij.openapi.fileEditor.FileEditor
import com.intellij.openapi.project.Project
import com.intellij.psi.PsiManager
import org.limepepper.lang.wikitext.annotation.BoundingBox

/**
 * The [StructureViewBuilder] returned by [PrpFileEditor]. The proofread-page
 * editor is a split of a text pane and a preview pane, so which structure the
 * Structure tool window shows depends on which pane is active:
 *
 * - text pane active → defer to the normal PSI structure (the language's
 *   `lang.psiStructureViewFactory`, reached through [PrpTextEditor])
 * - preview showing the reference scan → the bounding-box list
 *   ([PrpImageStructureRoot])
 * - preview showing the rendered HTML → a stub ([PrpInfoStructureElement]),
 *   since a parsed preview exposes no navigable structure yet
 *
 * When both previews are tiled together the active one is decided by focus (see
 * [PrpPreviewBrowser.activePreviewKind]). [PrpFileEditor] re-queries this
 * builder (by broadcasting the structure-changed signal) whenever the active
 * pane changes, so [activePane] is read afresh on every [createStructureView].
 */
class PrpStructureViewBuilder(
    private val editorHalf: PrpTextEditor,
    private val previewHalf: PrpPreviewBrowser,
    private val activePane: () -> PrpFileEditor.ActivePane,
    private val onNavigateBox: (BoundingBox) -> Unit,
) : StructureViewBuilder {

    override fun createStructureView(fileEditor: FileEditor?, project: Project): StructureView =
        when (activePane()) {
            PrpFileEditor.ActivePane.EDITOR -> editorStructureView(fileEditor, project)
            PrpFileEditor.ActivePane.PREVIEW_IMAGE -> previewStructureView(fileEditor, project, image = true)
            PrpFileEditor.ActivePane.PREVIEW_RENDER -> previewStructureView(fileEditor, project, image = false)
        }

    /**
     * Delegates to the text pane's own PSI structure builder. The composite
     * [fileEditor] is itself a `TextEditor` (it delegates `getEditor()` to the
     * text pane), so caret↔tree linking keeps working.
     */
    private fun editorStructureView(fileEditor: FileEditor?, project: Project): StructureView =
        editorHalf.structureViewBuilder?.createStructureView(fileEditor, project)
            ?: previewStructureView(fileEditor, project, image = false)

    private fun previewStructureView(fileEditor: FileEditor?, project: Project, image: Boolean): StructureView {
        val file = editorHalf.file
        // StructureViewModelBase needs a PsiFile; for a proofread page it
        // always resolves, but fall back to the text structure if it somehow
        // doesn't rather than crash the tool window.
        val psiFile = PsiManager.getInstance(project).findFile(file)
            ?: return editorHalf.structureViewBuilder?.createStructureView(fileEditor, project)
                ?: throw IllegalStateException("no PSI file and no fallback structure for $file")

        val root = if (image) {
            PrpImageStructureRoot(file, previewHalf.referenceImagePane.model, onNavigateBox)
        } else {
            PrpInfoStructureElement(
                key = file,
                title = "Rendered Preview",
                note = "No structure available",
            )
        }
        val model = PrpStructureViewModel(
            psiFile,
            root,
            boxModel = if (image) previewHalf.referenceImagePane.model else null,
        )
        return StructureViewComponent(fileEditor, model, project, /* showRootNode = */ true)
    }
}
