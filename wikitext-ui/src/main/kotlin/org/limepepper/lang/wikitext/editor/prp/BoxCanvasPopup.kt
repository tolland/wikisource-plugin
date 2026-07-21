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
 * [AnnotationCategory] or delete the box. Now that transcription text ranges
 * are managed independently in the editor (see [WtTextRangeManager]), the box
 * menu no longer carries any text-linking actions — the box is pure scan
 * geometry. Wired via
 * [org.limepepper.lang.wikitext.editor.prp.ReferenceImagePane.installPopupMenu].
 */
class BoxCanvasPopup(private val model: BoundingBoxModel) {
    fun menuFor(box: BoundingBox?): JPopupMenu? {
        if (box == null) {
            return null
        }
        // Inside JMenuItem.apply an unqualified `model` is the Swing
        // ButtonModel, not ours — hence the alias.
        val boxModel = model
        val menu = JPopupMenu()
        menu.add(categoryMenu(box))
        menu.addSeparator()
        menu.add(JMenuItem("Delete Box").apply {
            addActionListener { boxModel.remove(box.id) }
        })
        return menu
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
