package org.limepepper.lang.wikitext.editor.prp

import org.limepepper.lang.wikitext.annotation.AnnotationCategory
import org.limepepper.lang.wikitext.annotation.BoundingBox
import org.limepepper.lang.wikitext.annotation.BoundingBoxModel
import javax.swing.ButtonGroup
import javax.swing.JMenu
import javax.swing.JMenuItem
import javax.swing.JPopupMenu
import javax.swing.JRadioButtonMenuItem

/**
 * The image canvas's right-click menu for a bounding box: pick the OCR
 * [AnnotationCategory], link the box's content to one of the transcription
 * [TextRange]s (a dropdown over [rangeModel], persisted through
 * [linkModel]), or delete the box. Wired via
 * [org.limepepper.lang.wikitext.editor.prp.ReferenceImagePane.installPopupMenu].
 *
 * The linking pieces are optional so the popup still works for canvases that
 * have no text side (plain image files): with a null [rangeModel]/[linkModel]
 * the menu is category + delete only, as before.
 */
class BoxCanvasPopup(
    private val model: BoundingBoxModel,
    private val rangeModel: TextRangeModel? = null,
    private val linkModel: BoxLinkModel? = null,
    /** Human label for a range in the dropdown, e.g. a text snippet. */
    private val rangeLabel: ((TextRange) -> String)? = null,
    /** Called after linking (and by "Go to Linked Range") to reveal the range. */
    private val onRevealRange: ((rangeId: String) -> Unit)? = null,
) {
    fun menuFor(box: BoundingBox?): JPopupMenu? {
        if (box == null) {
            return null
        }
        // Inside JMenuItem.apply an unqualified `model` is the Swing
        // ButtonModel, not ours — hence the alias.
        val boxModel = model
        val menu = JPopupMenu()
        menu.add(categoryMenu(box))
        if (rangeModel != null && linkModel != null) {
            menu.addSeparator()
            menu.add(linkMenu(box, rangeModel, linkModel))
            val linkedRange = linkModel.rangeFor(box.id)
            menu.add(JMenuItem("Go to Linked Range").apply {
                isEnabled = linkedRange != null && onRevealRange != null
                addActionListener { linkedRange?.let { onRevealRange?.invoke(it) } }
            })
        }
        menu.addSeparator()
        menu.add(JMenuItem("Delete Box").apply {
            addActionListener { boxModel.remove(box.id) }
        })
        return menu
    }

    /**
     * The "Send to Text Range" dropdown — a radio group over the page's
     * current ranges plus "Not Linked". Ranges are listed in model order,
     * matching the palette order the editor chrome paints them in.
     */
    private fun linkMenu(box: BoundingBox, ranges: TextRangeModel, links: BoxLinkModel): JMenu {
        val menu = JMenu("Send to Text Range")
        val available = ranges.ranges()
        if (available.isEmpty()) {
            menu.add(JMenuItem("No text ranges on this page").apply { isEnabled = false })
            return menu
        }
        val linkedId = links.rangeFor(box.id)
        val group = ButtonGroup()
        menu.add(JRadioButtonMenuItem("Not Linked", linkedId == null).apply {
            group.add(this)
            addActionListener { links.unlink(box.id) }
        })
        menu.addSeparator()
        for ((index, range) in available.withIndex()) {
            val label = rangeLabel?.invoke(range) ?: defaultLabel(index, range)
            menu.add(JRadioButtonMenuItem(label, range.id == linkedId).apply {
                group.add(this)
                addActionListener {
                    links.link(box.id, range.id)
                    onRevealRange?.invoke(range.id)
                }
            })
        }
        return menu
    }

    private fun defaultLabel(index: Int, range: TextRange): String = when {
        range.isPoint -> "Range ${index + 1}: insertion point @ ${range.start}"
        else -> "Range ${index + 1}: ${range.start}–${range.end} (${range.length} chars)"
    }

    /** Region-category submenu — a radio group over [AnnotationCategory]. */
    private fun categoryMenu(box: BoundingBox): JMenu {
        val boxModel = model
        fun setCategory(category: AnnotationCategory?) {
            boxModel[box.id]?.let { boxModel.update(it.copy(category = category)) }
        }
        val menu = JMenu("Category")
        val group = ButtonGroup()
        menu.add(JRadioButtonMenuItem("None", box.category == null).apply {
            group.add(this)
            addActionListener { setCategory(null) }
        })
        for (category in AnnotationCategory.entries) {
            menu.add(JRadioButtonMenuItem(category.displayName, box.category == category).apply {
                group.add(this)
                addActionListener { setCategory(category) }
            })
        }
        return menu
    }
}
