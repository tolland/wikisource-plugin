package org.limepepper.lang.wikitext.editor.prp

import org.limepepper.lang.wikitext.annotation.AnnotationCategory
import org.limepepper.lang.wikitext.annotation.BoundingBox
import org.limepepper.lang.wikitext.annotation.BoundingBoxModel
import org.limepepper.lang.wikitext.vfs.backend.OcrBackendInfo
import org.limepepper.lang.wikitext.vfs.settings.OcrFavorite
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
    /** The site's OCR backends (loaded async by the host; empty = none yet). */
    private val ocrBackends: (() -> List<OcrBackendInfo>)? = null,
    /** Sends the box to a backend; the host owns cropping and the review UI. */
    private val onRunOcr: ((box: BoundingBox, choice: OcrMenuChoice) -> Unit)? = null,
    /** The project's favourite engine/language combinations, in menu order. */
    private val ocrFavorites: (() -> List<OcrFavorite>)? = null,
    /** Opens the favourites settings page. */
    private val onConfigureOcr: (() -> Unit)? = null,
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
        if (ocrBackends != null && onRunOcr != null) {
            menu.addSeparator()
            menu.add(ocrMenu(box, ocrBackends.invoke(), onRunOcr))
        }
        menu.addSeparator()
        menu.add(JMenuItem("Delete Box").apply {
            addActionListener { boxModel.remove(box.id) }
        })
        return menu
    }

    /**
     * The "Run OCR" submenu, built fresh on every right-click from the
     * project's favourites (see [OcrFavorite]) crossed with the backends
     * the site actually offers.
     *
     * It is a submenu rather than a flat run of items because the entries
     * are now a list of choices with a tail of management actions, and it
     * is generated rather than fixed because the useful engines depend on
     * both the wiki and the work — a stock Wikimedia OCR instance offers
     * hundreds of language/engine combinations and no static menu could
     * name the two or three that matter for the book in front of you.
     */
    private fun ocrMenu(
        box: BoundingBox,
        backends: List<OcrBackendInfo>,
        onRunOcr: (BoundingBox, OcrMenuChoice) -> Unit,
    ): JMenu {
        val menu = JMenu("Run OCR")
        if (backends.isEmpty()) {
            // Also the "not discovered yet" case: the host loads backends
            // asynchronously, so an empty list right after opening a page
            // is normal and the menu recovers on the next right-click.
            menu.add(JMenuItem("No OCR backends configured").apply { isEnabled = false })
        } else {
            val favorites = ocrFavorites?.invoke().orEmpty()
            val choices = OcrMenuChoice.resolve(favorites, backends)
            for (choice in choices) {
                menu.add(JMenuItem(choice.label).apply {
                    addActionListener { onRunOcr(box, choice) }
                })
            }
            if (choices.isEmpty()) {
                // Either there are no favourites yet, or every one of them
                // names a backend this site doesn't have. Falling back to
                // the raw backends keeps the feature usable either way.
                for (choice in OcrMenuChoice.defaults(backends)) {
                    menu.add(JMenuItem(choice.label).apply {
                        addActionListener { onRunOcr(box, choice) }
                    })
                }
            }
        }
        onConfigureOcr?.let { configure ->
            menu.addSeparator()
            menu.add(JMenuItem("Configure Favourites…").apply {
                addActionListener { configure() }
            })
        }
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
