package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.Disposable
import com.intellij.openapi.actionSystem.ActionGroup
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.DefaultActionGroup
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.editor.EditorCustomElementRenderer
import com.intellij.openapi.editor.Inlay
import com.intellij.openapi.editor.RangeMarker
import com.intellij.openapi.editor.ScrollType
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.editor.event.EditorMouseEvent
import com.intellij.openapi.editor.event.EditorMouseListener
import com.intellij.openapi.editor.event.EditorMouseMotionListener
import com.intellij.openapi.editor.markup.CustomHighlighterRenderer
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
import java.awt.BasicStroke
import java.awt.Color
import java.awt.Font
import java.awt.Graphics
import java.awt.Graphics2D
import java.awt.Rectangle
import java.awt.RenderingHints
import javax.swing.Icon
import kotlin.math.max

/**
 * The editor half of the independent text-range feature: renders each
 * [TextRange] from a [TextRangeModel] in the transcription body editor and
 * keeps the model in sync with the user's edits and gestures. Unlike the old
 * box-embedded anchor chrome, this owns no scan geometry — a range stands on
 * its own; a bounding box may later *refer* to it by sharing its id.
 *
 *  - each range shows as a DataGrip-style rounded border box around its text
 *    ([RangeBoxRenderer]); the range the caret sits in is emphasized (the
 *    "current" range), the rest are faint. An insertion point (start == end)
 *    shows as a thin caret bar plus a draggable chip;
 *  - a gutter icon carries the per-range menu ([RangeGutterIcon]): delete,
 *    reset the extent to the current selection, collapse to an insertion
 *    point at the caret;
 *  - small handle inlays bracket a range's start and end; dragging one adjusts
 *    that edge (see the mouse listeners). A point range has a single draggable
 *    chip instead;
 *  - while the document is edited the platform moves the [RangeMarker]s; a
 *    debounced pass writes the drifted offsets back into the model (which
 *    [WtTextRangeSync] then persists).
 *
 * Offset discipline mirrors the old anchor chrome: [model] offsets are
 * *body-relative* (the transcription body only), while [editor] shows the
 * whole `<noinclude>`-framed buffer with the header/footer guarded, so every
 * offset crossing the boundary is translated through [bodyStartOffset]. For an
 * unstructured buffer [bodyStartOffset] is `0` and everything degrades sanely.
 */
class WtTextRangeManager(
    private val editor: Editor,
    private val model: TextRangeModel,
    private val bodyStartOffset: () -> Int,
    private val bodyEndOffset: () -> Int,
    private val revidSupplier: () -> Long?,
) : Disposable {
    /**
     * Editor artifacts for one range. [modelStart]/[modelEnd] mirror the
     * range's offsets as of the last reconcile so a marker that merely
     * *drifted with edits* (writeback pending) is told apart from one whose
     * extent was *edited* (chrome must be rebuilt).
     */
    private class Chrome(
        val marker: RangeMarker,
        val highlighter: RangeHighlighter,
        val startHandle: Inlay<*>?,
        val endHandle: Inlay<*>?,
        val pointChip: Inlay<*>?,
        val colorIndex: Int,
        var modelStart: Int,
        var modelEnd: Int,
    )

    /** Which edge of which range a drag in progress is moving. */
    private enum class Edge { START, END, POINT }
    private class Drag(val rangeId: String, val edge: Edge)

    private val chromes = LinkedHashMap<String, Chrome>()
    private val writebackAlarm = Alarm(Alarm.ThreadToUse.SWING_THREAD, this)
    private val flashAlarm = Alarm(Alarm.ThreadToUse.SWING_THREAD, this)
    private var flashHighlighter: RangeHighlighter? = null
    private var drag: Drag? = null

    private val modelListener = object : TextRangeModel.Listener {
        override fun rangesChanged() = reconcile()

        override fun selectionChanged() = revealRange(model.selectedId)
    }

    init {
        model.addListener(modelListener)
        editor.document.addDocumentListener(object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) {
                writebackAlarm.cancelAllRequests()
                writebackAlarm.addRequest(::writeMarkerOffsetsBack, WRITEBACK_DELAY_MS)
                // The "current" range emphasis follows edits/caret; repaint.
                editor.contentComponent.repaint()
            }
        }, this)
        // Repaint the box emphasis as the caret moves between ranges.
        editor.caretModel.addCaretListener(
            object : com.intellij.openapi.editor.event.CaretListener {
                override fun caretPositionChanged(event: com.intellij.openapi.editor.event.CaretEvent) {
                    editor.contentComponent.repaint()
                }
            },
            this,
        )
        installDragListeners()
        editor.putUserData(CreateTextRangeAction.EDITOR_KEY, this)
        reconcile()
    }

    // ---- creation entry points (the editor action / gutter menu) ----------

    /**
     * Captures the current selection (or the caret, for an insertion point) as
     * a new range and adds it to the model. Offsets clamp into the editable
     * body so a range never lands in the guarded header/footer.
     */
    fun createFromSelection() {
        val (start, end) = currentBodyRange() ?: return
        val range = TextRange(start = start, end = end, anchorRevid = revidSupplier())
        if (!model.canPlace(range)) return
        model.add(range)
        editor.contentComponent.repaint()
    }

    /** Used by the editor action to disable creation for an invalid selection. */
    fun canCreateFromSelection(): Boolean {
        val (start, end) = currentBodyRange() ?: return false
        return model.canPlace(TextRange(start = start, end = end))
    }

    /** The current selection/caret as body-relative offsets, or null if it lies wholly outside the body. */
    private fun currentBodyRange(): Pair<Int, Int>? {
        val bodyStart = bodyStartOffset()
        val bodyEnd = bodyEndOffset().coerceAtLeast(bodyStart)
        val selection = editor.selectionModel
        val rawStart: Int
        val rawEnd: Int
        if (selection.hasSelection()) {
            rawStart = selection.selectionStart
            rawEnd = selection.selectionEnd
        } else {
            rawStart = editor.caretModel.offset
            rawEnd = rawStart
        }
        val start = rawStart.coerceIn(bodyStart, bodyEnd)
        val end = rawEnd.coerceIn(start, bodyEnd)
        return (start - bodyStart) to (end - bodyStart)
    }

    // ---- model → editor ---------------------------------------------------

    /** Rebuilds chrome where the model changed; drops the rest. */
    private fun reconcile() {
        if (editor.isDisposed) {
            return
        }
        val ranges = model.ranges().withIndex()
        val wantedIds = model.ranges().map { it.id }.toSet()

        for (id in chromes.keys.toList()) {
            if (id !in wantedIds) {
                removeChrome(id)
            }
        }
        for ((index, range) in ranges) {
            val existing = chromes[range.id]
            if (existing != null &&
                existing.modelStart == range.start &&
                existing.modelEnd == range.end &&
                existing.colorIndex == index &&
                existing.marker.isValid
            ) {
                continue // unchanged (marker drift is pending writeback, not a change)
            }
            removeChrome(range.id)
            chromes[range.id] = createChrome(range, index)
        }
    }

    private fun createChrome(range: TextRange, colorIndex: Int): Chrome {
        val bodyStart = bodyStartOffset()
        val length = editor.document.textLength
        val start = (range.start + bodyStart).coerceIn(bodyStart, length)
        val end = (range.end + bodyStart).coerceIn(start, length)
        val color = AnnotationPalette.colorFor(colorIndex)

        val marker = editor.document.createRangeMarker(start, end)
        val highlighter = editor.markupModel.addRangeHighlighter(
            start,
            end,
            HighlighterLayer.SELECTION - 1,
            null,
            HighlighterTargetArea.EXACT_RANGE,
        ).apply {
            customRenderer = RangeBoxRenderer(range.id, color)
            gutterIconRenderer = RangeGutterIcon(range.id, ColorIcon(GUTTER_ICON_PX, color))
        }

        var startHandle: Inlay<*>? = null
        var endHandle: Inlay<*>? = null
        var pointChip: Inlay<*>? = null
        if (start == end) {
            pointChip = editor.inlayModel.addInlineElement(start, true, HandleRenderer(range.id, Edge.POINT, color, point = true))
        } else {
            startHandle = editor.inlayModel.addInlineElement(start, false, HandleRenderer(range.id, Edge.START, color, point = false))
            endHandle = editor.inlayModel.addInlineElement(end, true, HandleRenderer(range.id, Edge.END, color, point = false))
        }
        return Chrome(marker, highlighter, startHandle, endHandle, pointChip, colorIndex, range.start, range.end)
    }

    private fun removeChrome(id: String) {
        val chrome = chromes.remove(id) ?: return
        if (!editor.isDisposed) {
            editor.markupModel.removeHighlighter(chrome.highlighter)
        }
        chrome.startHandle?.let(Disposer::dispose)
        chrome.endHandle?.let(Disposer::dispose)
        chrome.pointChip?.let(Disposer::dispose)
        chrome.marker.dispose()
    }

    // ---- editor → model ---------------------------------------------------

    /**
     * Persists marker drift: after edits settle, any range whose marker moved
     * gets its new body-relative offsets written into the model. A marker
     * invalidated by a whole-buffer replacement is rebuilt at the range's
     * stored offsets on the next [reconcile].
     */
    private fun writeMarkerOffsetsBack() {
        if (editor.isDisposed) {
            return
        }
        var invalidated = false
        for ((id, chrome) in chromes) {
            val range = model[id] ?: continue
            if (!chrome.marker.isValid) {
                invalidated = true
                continue
            }
            val bodyStart = bodyStartOffset()
            val start = (chrome.marker.startOffset - bodyStart).coerceAtLeast(0)
            val end = (chrome.marker.endOffset - bodyStart).coerceAtLeast(start)
            if (start != range.start || end != range.end) {
                val updated = range.copy(start = start, end = end)
                if (!model.canPlace(updated)) continue
                chrome.modelStart = start
                chrome.modelEnd = end
                model.update(updated)
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

    // ---- drag handles ------------------------------------------------------

    private fun installDragListeners() {
        editor.addEditorMouseListener(object : EditorMouseListener {
            override fun mousePressed(event: EditorMouseEvent) {
                val handle = event.inlay?.renderer as? HandleRenderer ?: return
                drag = Drag(handle.rangeId, handle.edge)
                event.consume()
            }

            override fun mouseReleased(event: EditorMouseEvent) {
                if (drag != null) {
                    drag = null
                    event.consume()
                }
            }
        }, this)

        editor.addEditorMouseMotionListener(object : EditorMouseMotionListener {
            override fun mouseDragged(event: EditorMouseEvent) {
                val active = drag ?: return
                dragTo(active, event.mouseEvent.point)
                event.consume()
            }
        }, this)
    }

    private fun dragTo(active: Drag, point: java.awt.Point) {
        val range = model[active.rangeId] ?: return
        val bodyStart = bodyStartOffset()
        val bodyEnd = bodyEndOffset()
        val offset = editor.logicalPositionToOffset(editor.xyToLogicalPosition(point))
            .coerceIn(bodyStart, bodyEnd) - bodyStart
        val updated = when (active.edge) {
            Edge.START -> range.copy(start = offset.coerceAtMost(range.end))
            Edge.END -> range.copy(end = offset.coerceAtLeast(range.start))
            Edge.POINT -> range.copy(start = offset, end = offset)
        }
        if (updated != range) {
            if (model.canPlace(updated)) model.update(updated)
        }
    }

    // ---- selection / reveal ------------------------------------------------

    /** Scroll to a range and flash it (e.g. a box referring to it was selected). */
    private fun revealRange(rangeId: String?) {
        val chrome = rangeId?.let(chromes::get) ?: return
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

    private fun caretInside(start: Int, end: Int): Boolean {
        val caret = editor.caretModel.offset
        return if (start == end) caret == start else caret in start..end
    }

    // ---- renderers ---------------------------------------------------------

    /** DataGrip-style rounded border around a range; emphasized when current. */
    private inner class RangeBoxRenderer(
        private val rangeId: String,
        private val color: Color,
    ) : CustomHighlighterRenderer {
        override fun paint(editor: Editor, highlighter: RangeHighlighter, g: Graphics) {
            val start = highlighter.startOffset
            val end = highlighter.endOffset
            val g2 = g as Graphics2D
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            val current = caretInside(start, end)
            g2.color = if (current) color else color.withAlpha(FAINT_BORDER_ALPHA)
            g2.stroke = BasicStroke(if (current) 1.5f else 1.0f)
            val lineHeight = editor.lineHeight

            if (start == end) {
                val p = editor.offsetToXY(start)
                g2.fillRect(p.x - 1, p.y, 2, lineHeight)
                return
            }
            if (current) {
                // A faint wash inside the current range, DataGrip-like.
                g2.color = color.withAlpha(CURRENT_FILL_ALPHA)
            }
            val doc = editor.document
            val startLine = doc.getLineNumber(start)
            val endLine = doc.getLineNumber(end)
            for (line in startLine..endLine) {
                val segStart = if (line == startLine) start else doc.getLineStartOffset(line)
                val segEnd = if (line == endLine) end else doc.getLineEndOffset(line)
                val a = editor.offsetToXY(segStart)
                val b = editor.offsetToXY(segEnd)
                val x = a.x - SEG_PAD
                val w = max(b.x - a.x, MIN_SEG_PX) + 2 * SEG_PAD
                if (current) {
                    g2.color = color.withAlpha(CURRENT_FILL_ALPHA)
                    g2.fillRoundRect(x, a.y, w, lineHeight, ARC, ARC)
                }
                g2.color = if (current) color else color.withAlpha(FAINT_BORDER_ALPHA)
                g2.drawRoundRect(x, a.y, w, lineHeight, ARC, ARC)
            }
        }
    }

    /** A draggable knob bracketing a range edge (or marking a point). */
    private class HandleRenderer(
        val rangeId: String,
        val edge: Edge,
        private val color: Color,
        private val point: Boolean,
    ) : EditorCustomElementRenderer {
        override fun calcWidthInPixels(inlay: Inlay<*>): Int = if (point) POINT_CHIP_PX else HANDLE_PX

        override fun paint(inlay: Inlay<*>, g: Graphics, targetRegion: Rectangle, textAttributes: TextAttributes) {
            val g2 = g as Graphics2D
            g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON)
            val d = HANDLE_PX
            val y = targetRegion.y + (targetRegion.height - d) / 2
            g2.color = color
            if (point) {
                // A small diamond for an insertion point.
                val cx = targetRegion.x + POINT_CHIP_PX / 2
                val cy = targetRegion.y + targetRegion.height / 2
                val xs = intArrayOf(cx, cx + d / 2, cx, cx - d / 2)
                val ys = intArrayOf(cy - d / 2, cy, cy + d / 2, cy)
                g2.fillPolygon(xs, ys, 4)
            } else {
                g2.fillRoundRect(targetRegion.x + 1, y, d - 2, d, d / 2, d / 2)
            }
        }
    }

    /** Gutter icon carrying the per-range menu. */
    private inner class RangeGutterIcon(
        private val rangeId: String,
        private val icon: Icon,
    ) : GutterIconRenderer() {
        override fun getIcon(): Icon = icon

        override fun getTooltipText(): String {
            val range = model[rangeId] ?: return "Text range"
            val kind = if (range.isPoint) "Insertion point" else "Text range (${range.length} chars)"
            val stale = revidSupplier()?.let { current ->
                range.anchorRevid?.let { if (it != current) " — stale (rev $it)" else "" } ?: ""
            } ?: ""
            return kind + stale
        }

        override fun isNavigateAction(): Boolean = true

        override fun getClickAction(): AnAction = object : AnAction("Go to Text Range") {
            override fun actionPerformed(e: AnActionEvent) = revealRange(rangeId)
        }

        override fun getPopupMenuActions(): ActionGroup {
            val group = DefaultActionGroup()
            group.add(object : AnAction("Reset to Current Selection") {
                override fun actionPerformed(e: AnActionEvent) {
                    val range = model[rangeId] ?: return
                    val (start, end) = currentBodyRange() ?: return
                    val updated = range.copy(start = start, end = end, anchorRevid = revidSupplier())
                    if (model.canPlace(updated)) model.update(updated)
                }
            })
            group.add(object : AnAction("Collapse to Insertion Point at Caret") {
                override fun actionPerformed(e: AnActionEvent) {
                    val range = model[rangeId] ?: return
                    val bodyStart = bodyStartOffset()
                    val at = editor.caretModel.offset.coerceIn(bodyStart, bodyEndOffset()) - bodyStart
                    val updated = range.copy(start = at, end = at, anchorRevid = revidSupplier())
                    if (model.canPlace(updated)) model.update(updated)
                }
            })
            group.addSeparator()
            group.add(object : AnAction("Delete Text Range") {
                override fun actionPerformed(e: AnActionEvent) = model.remove(rangeId)
            })
            return group
        }

        override fun equals(other: Any?): Boolean = other is RangeGutterIcon && other.rangeId == rangeId

        override fun hashCode(): Int = rangeId.hashCode()
    }

    override fun dispose() {
        if (editor.getUserData(CreateTextRangeAction.EDITOR_KEY) === this) {
            editor.putUserData(CreateTextRangeAction.EDITOR_KEY, null)
        }
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

    private companion object {
        const val WRITEBACK_DELAY_MS = 700
        const val FLASH_MS = 700
        const val FLASH_BG_ALPHA = 90
        const val FAINT_BORDER_ALPHA = 90
        const val CURRENT_FILL_ALPHA = 28
        const val GUTTER_ICON_PX = 10
        const val HANDLE_PX = 8
        const val POINT_CHIP_PX = 10
        const val ARC = 6
        const val SEG_PAD = 2
        const val MIN_SEG_PX = 3
    }
}
