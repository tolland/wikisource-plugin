package org.limepepper.lang.wikitext.annotation

import java.util.UUID
import kotlin.math.abs
import kotlin.math.min

/**
 * One annotation rectangle, in image pixel coordinates (the coordinate space
 * of the full-resolution scan, independent of the on-screen zoom).
 *
 * Immutable: interactions (move/resize) produce new instances via [copy],
 * which keeps undo/persistence/diffing trivial. [id] is the stable identity
 * that outlives geometry changes — it is the join key to everything outside
 * the canvas (persisted rows, text anchors).
 *
 * [category] classifies the region for the OCR pipeline (see
 * [AnnotationCategory]); null = uncategorized.
 *
 * A box may carry a text anchor: character offsets into the transcription
 * text the box's region corresponds to ([textStart] == [textEnd] marks an
 * insertion point, < a replace range; both null = unlinked). The canvas
 * never edits these — the editor-side anchor chrome owns them — but they
 * live on the box so one model object is the whole annotation. Server-side
 * the two halves are separate resources joined by [id].
 */
data class BoundingBox(
    val id: String = UUID.randomUUID().toString(),
    val x: Double,
    val y: Double,
    val width: Double,
    val height: Double,
    val label: String? = null,
    val category: AnnotationCategory? = null,
    val textStart: Int? = null,
    val textEnd: Int? = null,
    /** Revision the offsets were computed against; null = unknown/local. */
    val anchorRevid: Long? = null,
) {
    val linked: Boolean get() = textStart != null && textEnd != null

    val right: Double get() = x + width
    val bottom: Double get() = y + height

    fun contains(px: Double, py: Double): Boolean =
        px >= x && px <= right && py >= y && py <= bottom

    val area: Double get() = width * height

    companion object {
        /** Normalized box spanning two corner points, in any drag direction. */
        fun fromCorners(x1: Double, y1: Double, x2: Double, y2: Double, id: String = UUID.randomUUID().toString()): BoundingBox =
            BoundingBox(
                id = id,
                x = min(x1, x2),
                y = min(y1, y2),
                width = abs(x2 - x1),
                height = abs(y2 - y1),
            )
    }
}
