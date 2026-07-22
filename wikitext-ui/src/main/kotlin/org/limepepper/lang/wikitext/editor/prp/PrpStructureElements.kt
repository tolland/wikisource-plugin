package org.limepepper.lang.wikitext.editor.prp

import com.intellij.icons.AllIcons
import com.intellij.ide.projectView.PresentationData
import com.intellij.ide.structureView.StructureViewTreeElement
import com.intellij.ide.util.treeView.smartTree.SortableTreeElement
import com.intellij.ide.util.treeView.smartTree.TreeElement
import com.intellij.navigation.ItemPresentation
import com.intellij.openapi.vfs.VirtualFile
import org.limepepper.lang.wikitext.annotation.BoundingBox
import org.limepepper.lang.wikitext.annotation.BoundingBoxModel
import kotlin.math.roundToInt

/**
 * Structure-view tree elements for the proofread-page *preview* side (the
 * right pane). Unlike [org.limepepper.lang.wikitext.structure.WtStructureViewElement]
 * these are not backed by PSI — the preview has no syntax tree — so they wrap
 * the pane's own model (bounding boxes) or are pure informational stubs.
 *
 * Wholly owned by [PrpStructureViewModel]; kept in one file as the small set
 * of leaf/root nodes that model builds.
 */

/**
 * Root node for the reference-image structure: the scan itself, with one
 * child per [BoundingBox] drawn over it. Children are ordered top-to-bottom,
 * left-to-right so the tree reads in reading order rather than creation order.
 */
class PrpImageStructureRoot(
    private val file: VirtualFile,
    private val model: BoundingBoxModel,
    private val onNavigateBox: (BoundingBox) -> Unit,
) : StructureViewTreeElement {

    override fun getValue(): Any = file

    override fun getPresentation(): ItemPresentation {
        val count = model.boxes().size
        val suffix = if (count == 1) "region" else "regions"
        return PresentationData("Reference Image", "$count $suffix", AllIcons.FileTypes.Image, null)
    }

    override fun getChildren(): Array<TreeElement> =
        model.boxes()
            .sortedWith(compareBy({ it.y }, { it.x }))
            .map { PrpBoxStructureElement(it, onNavigateBox) }
            .toTypedArray()

    override fun navigate(requestFocus: Boolean) = Unit

    override fun canNavigate(): Boolean = false

    override fun canNavigateToSource(): Boolean = false
}

/**
 * A single bounding box in the tree. Navigating reveals it on the scan (and,
 * when the box carries a text anchor, moves the transcription caret to the
 * linked region) via [onNavigate].
 */
class PrpBoxStructureElement(
    private val box: BoundingBox,
    private val onNavigate: (BoundingBox) -> Unit,
) : StructureViewTreeElement, SortableTreeElement {

    override fun getValue(): Any = box

    override fun getPresentation(): ItemPresentation =
        PresentationData(title(), coordinates(), AllIcons.Nodes.Tag, null)

    override fun getChildren(): Array<TreeElement> = TreeElement.EMPTY_ARRAY

    override fun getAlphaSortKey(): String = title()

    override fun navigate(requestFocus: Boolean) = onNavigate(box)

    override fun canNavigate(): Boolean = true

    /** Only a linked box has a transcription offset to jump the caret to. */
    override fun canNavigateToSource(): Boolean = false // box.linked

    private fun title(): String =
        box.label?.takeIf { it.isNotBlank() }
            ?: box.category?.displayName
            ?: "Region"

    private fun coordinates(): String {
        val x = box.x.roundToInt()
        val y = box.y.roundToInt()
        val w = box.width.roundToInt()
        val h = box.height.roundToInt()
        //val linkMark = if (box.linked) " • linked" else ""
        val linkMark = if (false) " • linked" else ""
        return "($x, $y) ${w}×$h$linkMark"
    }
}

/**
 * A non-navigable informational node — the stub shown when a preview mode has
 * no real structure to offer (currently the rendered-HTML preview).
 */
class PrpInfoStructureElement(
    private val key: Any,
    private val title: String,
    private val note: String?,
) : StructureViewTreeElement {

    override fun getValue(): Any = key

    override fun getPresentation(): ItemPresentation =
        PresentationData(title, note, AllIcons.General.Information, null)

    override fun getChildren(): Array<TreeElement> = TreeElement.EMPTY_ARRAY

    override fun navigate(requestFocus: Boolean) = Unit

    override fun canNavigate(): Boolean = false

    override fun canNavigateToSource(): Boolean = false
}
