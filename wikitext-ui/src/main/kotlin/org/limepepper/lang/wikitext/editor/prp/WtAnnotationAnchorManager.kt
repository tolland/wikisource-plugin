package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.Disposable
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.editor.Inlay
import com.intellij.openapi.editor.EditorCustomElementRenderer
import com.intellij.openapi.editor.RangeMarker
import com.intellij.openapi.editor.ScrollType
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.editor.markup.EffectType
import com.intellij.openapi.editor.markup.GutterIconRenderer
import com.intellij.openapi.editor.markup.HighlighterLayer
import com.intellij.openapi.editor.markup.HighlighterTargetArea
import com.intellij.openapi.editor.markup.RangeHighlighter
import com.intellij.openapi.editor.markup.TextAttributes
import com.intellij.openapi.util.Disposer
import com.intellij.util.Alarm
import com.intellij.util.ui.ColorIcon
import org.limepepper.lang.wikitext.annotation.AnnotationPalette
import org.limepepper.lang.wikitext.annotation.AnnotationPalette.withAlpha
import org.limepepper.lang.wikitext.annotation.BoundingBox
import org.limepepper.lang.wikitext.annotation.BoundingBoxModel
import java.awt.Font
import java.awt.Graphics
import java.awt.Graphics2D
import java.awt.Rectangle
import java.awt.RenderingHints
import javax.swing.Icon
import javax.swing.JMenuItem
import javax.swing.JPopupMenu

/**
 * The editor half of box↔text linking: renders each linked box's text
 * anchor in the transcription (body) editor and keeps the two sides
 * consistent.
 *
 *  - a *range* anchor (textStart < textEnd, "replace with OCR") shows as a
 *    persistent range highlight in the box's color plus a gutter dot —
 *    visible even while focus is in the image pane, which editor selection
 *    is not;
 *  - an *insertion point* (textStart == textEnd, "insert OCR here") has no
 *    extent to highlight, so it shows as an inline chip (inlay) instead,
 *    plus the same gutter dot;
 *  - clicking the gutter dot reveals the box in the image pane
 *    ([onRevealBox]); selecting a linked box in the canvas scrolls the
 *    editor to its anchor and flashes it — the two-way sync;
 *  - while the document is edited, the platform moves the [RangeMarker]s;
 *    a debounced pass writes the moved offsets back into the model, which
 *    [WtAnnotationSync] then persists. Offsets are therefore *body-text*
 *    offsets — [editor] shows the whole `<noinclude>`-framed buffer with the
 *    header/footer guarded (see `PrpTextEditor`), so every offset exchanged
 *    with [model] is translated through [bodyStartOffset] to stay
 *    body-relative on the wire; only [editor]'s own marker/caret/selection
 *    offsets are whole-buffer (for an unstructured buffer [bodyStartOffset]
 *    is `0`, so they degrade sanely).
 *
 * Also owns the canvas's right-click menu ([createPopupMenu]) — the link/
 * unlink actions need the editor's caret and selection, which live here.
 */
class WtAnnotationAnchorManager(
    private val editor: Editor,
    private val model: BoundingBoxModel,
    private val bodyStartOffset: () -> Int,
    private val revidSupplier: () -> Long?,
    private val onRevealBox: (String) -> Unit,
) : Disposable {
    /**
     * The editor artifacts for one linked box. [modelStart]/[modelEnd]
     * mirror the box's offsets as of the last reconcile, so a marker that
     * has merely *drifted with edits* (writeback pending) is distinguishable
     * from a box whose anchor was *re-linked* (chrome must be rebuilt).
     */
    private class AnchorChrome(
        val marker: RangeMarker,
        val highlighter: RangeHighlighter,
        val inlay: Inlay<*>?,
        val colorIndex: Int,
        val label: String?,
        var modelStart: Int,
        var modelEnd: Int,
    )

    private val chromes = LinkedHashMap<String, AnchorChrome>()
    private val writebackAlarm = Alarm(Alarm.ThreadToUse.SWING_THREAD, this)
    private val flashAlarm = Alarm(Alarm.ThreadToUse.SWING_THREAD, this)
    private var flashHighlighter: RangeHighlighter? = null

    private val modelListener = object : BoundingBoxModel.Listener {
        override fun boxesChanged() = reconcile()

        override fun selectionChanged() = revealAnchorOf(model.selectedId)
    }

    init {
        model.addListener(modelListener)
        editor.document.addDocumentListener(object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) {
                writebackAlarm.cancelAllRequests()
                writebackAlarm.addRequest(::writeMarkerOffsetsBack, WRITEBACK_DELAY_MS)
            }
        }, this)
        reconcile()
    }

    // ---- model → editor ---------------------------------------------------

    /** Rebuilds chrome where the model's anchors changed; drops the rest. */
    private fun reconcile() {
        if (editor.isDisposed) {
            return
        }
        val linked = model.boxes().withIndex().filter { it.value.linked }
        val wantedIds = linked.map { it.value.id }.toSet()

        for (id in chromes.keys.toList()) {
            if (id !in wantedIds) {
                removeChrome(id)
            }
        }
        for ((index, box) in linked) {
            val existing = chromes[box.id]
            if (existing != null &&
                existing.modelStart == box.textStart &&
                existing.modelEnd == box.textEnd &&
                existing.colorIndex == index &&
                existing.label == box.label &&
                existing.marker.isValid
            ) {
                continue // unchanged (marker drift is pending writeback, not a change)
            }
            removeChrome(box.id)
            chromes[box.id] = createChrome(box, index)
        }
    }

    private fun createChrome(box: BoundingBox, colorIndex: Int): AnchorChrome {
        val bodyStart = bodyStartOffset()
        val length = editor.document.textLength
        val start = (requireNotNull(box.textStart) + bodyStart).coerceIn(bodyStart, length)
        val end = (requireNotNull(box.textEnd) + bodyStart).coerceIn(start, length)
        val color = AnnotationPalette.colorFor(colorIndex)

        val marker = editor.document.createRangeMarker(start, end)
        val attributes = if (end > start) {
            TextAttributes(null, color.withAlpha(RANGE_BG_ALPHA), color, EffectType.BOXED, Font.PLAIN)
        } else {
            null // an insertion point has no extent; the inlay is the visual
        }
        val highlighter = editor.markupModel.addRangeHighlighter(
            start,
            end,
            HighlighterLayer.ADDITIONAL_SYNTAX,
            attributes,
            HighlighterTargetArea.EXACT_RANGE,
        ).apply {
            gutterIconRenderer = AnchorGutterIcon(box.id, ColorIcon(GUTTER_ICON_PX, color), box.label)
        }
        val inlay = if (end == start) {
            editor.inlayModel.addInlineElement(
                start,
                false,
                InsertChipRenderer(color, box.label ?: "insert"),
            )
        } else {
            null
        }
        return AnchorChrome(marker, highlighter, inlay, colorIndex, box.label, box.textStart!!, box.textEnd!!)
    }

    private fun removeChrome(id: String) {
        val chrome = chromes.remove(id) ?: return
        if (!editor.isDisposed) {
            editor.markupModel.removeHighlighter(chrome.highlighter)
        }
        chrome.inlay?.let(Disposer::dispose)
        chrome.marker.dispose()
    }

    // ---- editor → model ---------------------------------------------------

    /**
     * Persists marker drift: after edits settle, any anchor whose marker
     * moved gets its new offsets written into the model (and from there to
     * the sidecar). A marker invalidated by a whole-buffer replacement
     * (raw-mode/external edits swap the body text wholesale) is rebuilt at
     * the box's stored offsets on the next [reconcile].
     */
    private fun writeMarkerOffsetsBack() {
        if (editor.isDisposed) {
            return
        }
        var invalidated = false
        for ((id, chrome) in chromes) {
            val box = model[id] ?: continue
            if (!chrome.marker.isValid) {
                invalidated = true
                continue
            }
            val bodyStart = bodyStartOffset()
            val start = chrome.marker.startOffset - bodyStart
            val end = chrome.marker.endOffset - bodyStart
            if (start != box.textStart || end != box.textEnd) {
                chrome.modelStart = start
                chrome.modelEnd = end
                model.update(box.copy(textStart = start, textEnd = end))
            }
        }
        if (invalidated) {
            for (id in chromes.keys.toList()) {
                if (!chromes.getValue(id).marker.isValid) {
                    removeChrome(id)
                }
            }
            reconcile()
        }
    }

    // ---- two-way navigation ------------------------------------------------

    /** Canvas → editor: scroll to the selected box's anchor and flash it. */
    private fun revealAnchorOf(boxId: String?) {
        val chrome = boxId?.let(chromes::get) ?: return
        if (editor.isDisposed || !chrome.marker.isValid) {
            return
        }
        val start = chrome.marker.startOffset
        editor.scrollingModel.scrollTo(editor.offsetToLogicalPosition(start), ScrollType.CENTER)
        flash(start, chrome.marker.endOffset, chrome.colorIndex)
    }

    private fun flash(start: Int, end: Int, colorIndex: Int) {
        flashHighlighter?.let(editor.markupModel::removeHighlighter)
        val color = AnnotationPalette.colorFor(colorIndex)
        val flashEnd = if (end > start) end else (start + 1).coerceAtMost(editor.document.textLength)
        flashHighlighter = editor.markupModel.addRangeHighlighter(
            start,
            flashEnd,
            HighlighterLayer.SELECTION + 1,
            TextAttributes(null, color.withAlpha(FLASH_BG_ALPHA), null, null, Font.PLAIN),
            HighlighterTargetArea.EXACT_RANGE,
        )
        flashAlarm.cancelAllRequests()
        flashAlarm.addRequest({
            flashHighlighter?.let {
                if (!editor.isDisposed) {
                    editor.markupModel.removeHighlighter(it)
                }
                flashHighlighter = null
            }
        }, FLASH_MS)
    }

    /** Editor gutter → canvas. */
    private inner class AnchorGutterIcon(
        private val boxId: String,
        private val icon: Icon,
        private val label: String?,
    ) : GutterIconRenderer() {
        override fun getIcon(): Icon = icon

        override fun getTooltipText(): String = label?.let { "Scan region: $it" } ?: "Scan region"

        override fun isNavigateAction(): Boolean = true

        override fun getClickAction(): AnAction = object : AnAction("Show Scan Region") {
            override fun actionPerformed(e: AnActionEvent) = onRevealBox(boxId)
        }

        override fun equals(other: Any?): Boolean =
            other is AnchorGutterIcon && other.boxId == boxId

        override fun hashCode(): Int = boxId.hashCode()
    }

    // ---- link actions (the canvas's right-click menu) -----------------------

    /**
     * The menu for a right-click on [box] in the image pane. Reads the
     * body editor's caret/selection at action time — both survive the
     * focus transfer to the canvas, unlike their painted appearance.
     */
    fun createPopupMenu(box: BoundingBox?): JPopupMenu? {
        if (box == null) {
            return null
        }
        // Inside JMenuItem.apply an unqualified `model` is the Swing
        // ButtonModel, not ours — hence the alias.
        val boxModel = model
        val menu = JPopupMenu()
        val caret = editor.caretModel.offset
        menu.add(JMenuItem("Link to Cursor (insert point)").apply {
            addActionListener { link(box.id, caret, caret) }
        })
        with(editor.selectionModel) {
            if (hasSelection()) {
                menu.add(JMenuItem("Link to Selection (replace range)").apply {
                    addActionListener { link(box.id, selectionStart, selectionEnd) }
                })
            }
        }
        if (box.linked) {
            menu.add(JMenuItem("Go to Linked Text").apply {
                addActionListener { revealAnchorOf(box.id) }
            })
            menu.add(JMenuItem("Unlink from Text").apply {
                addActionListener {
                    boxModel[box.id]?.let { current ->
                        boxModel.update(current.copy(textStart = null, textEnd = null, anchorRevid = null))
                    }
                }
            })
        }
        menu.addSeparator()
        menu.add(JMenuItem("Delete Box").apply {
            addActionListener { boxModel.remove(box.id) }
        })
        return menu
    }

    private fun link(boxId: String, start: Int, end: Int) {
        val box = model[boxId] ?: return
        val bodyStart = bodyStartOffset()
        model.update(
            box.copy(textStart = start - bodyStart, textEnd = end - bodyStart, anchorRevid = revidSupplier()),
        )
        revealAnchorOf(boxId)
    }

    override fun dispose() {
        model.removeListener(modelListener)
        for (id in chromes.keys.toList()) {
            removeChrome(id)
        }
        flashHighlighter?.let {
            if (!editor.isDisposed) {
                editor.markupModel.removeHighlighter(it)
            }
        }
    }

    /** The inline chip marking an insertion-point anchor. */
    private class InsertChipRenderer(
        private val color: java.awt.Color,
        private val text: String,
    ) : EditorCustomElementRenderer {
        override fun calcWidthInPixels(inlay: Inlay<*>): Int {
            val metrics = inlay.editor.contentComponent.getFontMetrics(chipFont(inlay))
            return metrics.stringWidth(text) + 2 * CHIP_PADDING_PX + CHIP_GAP_PX
        }

        override fun paint(inlay: Inlay<*>, g: Graphics, targetRegion: Rectangle, textAttributes: TextAttributes) {
            val g2 = g as Graphics2D
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            val font = chipFont(inlay)
            val metrics = inlay.editor.contentComponent.getFontMetrics(font)
            val width = targetRegion.width - CHIP_GAP_PX
            val height = metrics.height
            val y = targetRegion.y + (targetRegion.height - height) / 2
            g2.color = color.withAlpha(50)
            g2.fillRoundRect(targetRegion.x, y, width, height, height, height)
            g2.color = color
            g2.drawRoundRect(targetRegion.x, y, width, height, height, height)
            g2.font = font
            g2.drawString(text, targetRegion.x + CHIP_PADDING_PX, y + metrics.ascent)
        }

        private fun chipFont(inlay: Inlay<*>): Font {
            val editorFont = inlay.editor.colorsScheme.getFont(com.intellij.openapi.editor.colors.EditorFontType.PLAIN)
            return editorFont.deriveFont(editorFont.size2D - 2f)
        }
    }

    private companion object {
        const val WRITEBACK_DELAY_MS = 700
        const val FLASH_MS = 700
        const val RANGE_BG_ALPHA = 40
        const val FLASH_BG_ALPHA = 90
        const val GUTTER_ICON_PX = 10
        const val CHIP_PADDING_PX = 4
        const val CHIP_GAP_PX = 3
    }
}
