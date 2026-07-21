package org.limepepper.lang.wikitext.editor.prp

import java.util.UUID

/**
 * One persistable range of the transcription *body* text — the editor-side
 * mirror of the sidecar's `TextTargetAnchor` (`/pages/text-anchors`). It is a
 * first-class, independently managed object: a scan bounding box *may* refer
 * to a range by sharing its [id], but a range never depends on a box (create
 * the range in the editor, draw the region later — or never).
 *
 * Immutable; edits produce new instances via [copy] so undo/diffing stay
 * trivial. [id] is the stable identity that survives extent changes and is the
 * join key to anything outside the editor (persisted rows, a box that refers
 * to it).
 *
 * [start] == [end] marks an *insertion point* (a caret target for inserted
 * text); [start] < [end] marks a *replace range*. Offsets are character
 * offsets into the body text as of [anchorRevid]; a mismatch with the page's
 * current revid means the range is stale and must be surfaced, not trusted.
 */
data class TextRange(
    val id: String = UUID.randomUUID().toString(),
    val start: Int,
    val end: Int,
    /** Revision the offsets were computed against; null = unknown/local. */
    val anchorRevid: Long? = null,
) {
    init {
        require(start in 0..end) { "need 0 <= start <= end, got $start..$end" }
    }

    val isPoint: Boolean get() = start == end

    val length: Int get() = end - start
}
