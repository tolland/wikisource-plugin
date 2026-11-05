package org.limepepper.lang.wikitext.editor.prp

import com.intellij.ide.structureView.StructureViewModel
import com.intellij.ide.structureView.StructureViewModelBase
import com.intellij.ide.structureView.StructureViewTreeElement
import com.intellij.psi.PsiFile
import org.limepepper.lang.wikitext.annotation.BoundingBoxModel

/**
 * Structure-view model for the proofread-page *preview* pane. The text pane
 * keeps using the ordinary PSI structure (via [PrpTextEditor]); this model
 * backs the preview side only, where there is no syntax tree:
 *
 * - reference-image mode → a [PrpImageStructureRoot] listing the scan's
 *   bounding boxes, refreshed live off the shared [BoundingBoxModel]
 * - rendered-preview mode → a [PrpInfoStructureElement] stub (no structure yet)
 *
 * [psiFile] is still required by [StructureViewModelBase], but the tree itself
 * is driven by [root], not by the PSI.
 */
class PrpStructureViewModel(
    psiFile: PsiFile,
    root: StructureViewTreeElement,
    private val boxModel: BoundingBoxModel?,
) : StructureViewModelBase(psiFile, null, root),
    StructureViewModel.ElementInfoProvider {

    // When the boxes change on the canvas, rebuild the tree so it stays in
    // step with what the proofreader sees on the scan.
    private val boxListener = object : BoundingBoxModel.Listener {
        override fun boxesChanged() = fireModelUpdate()
    }

    init {
        boxModel?.addListener(boxListener)
    }

    override fun isAlwaysShowsPlus(element: StructureViewTreeElement): Boolean = false

    override fun isAlwaysLeaf(element: StructureViewTreeElement): Boolean =
        element is PrpBoxStructureElement || element is PrpInfoStructureElement

    override fun dispose() {
        boxModel?.removeListener(boxListener)
        super.dispose()
    }
}
