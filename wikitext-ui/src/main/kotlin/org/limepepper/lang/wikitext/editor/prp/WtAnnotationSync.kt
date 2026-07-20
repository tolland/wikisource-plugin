package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.util.Alarm
import org.limepepper.lang.wikitext.annotation.BoundingBox
import org.limepepper.lang.wikitext.annotation.BoundingBoxModel
import org.limepepper.lang.wikitext.vfs.backend.PageAnnotation
import org.limepepper.lang.wikitext.vfs.backend.PageTextAnchor
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService

private val SYNC_LOG = logger<WtAnnotationSync>()

/**
 * Write-behind persistence for the reference pane's [BoundingBoxModel]:
 * observes the model, debounces the change storm a drag produces, and
 * pushes the net difference to the sidecar. Failures keep the difference
 * dirty and retry, so a briefly-down sidecar loses nothing (short of
 * closing the editor mid-outage).
 *
 * A [BoundingBox] carries the whole annotation, but server-side it is two
 * resources joined by the box id — the bounding box (geometry, label,
 * category → /pages/annotations) and the text anchor (offsets owned by
 * [WtAnnotationAnchorManager] → /pages/text-anchors) — so the diff is
 * split: each half is PUT/DELETEd only when that half changed. Deleting a
 * box deletes both halves server-side in one call.
 *
 * EDT discipline: the model is EDT-owned, so diffing happens on the EDT
 * (via [alarm]) and only the HTTP calls hop to a pooled thread.
 */
class WtAnnotationSync(
    private val model: BoundingBoxModel,
    private val path: String,
) : Disposable {
    /** Last state the server acknowledged, by annotation id. */
    private val synced = HashMap<String, BoundingBox>()

    private val alarm = Alarm(Alarm.ThreadToUse.SWING_THREAD, this)
    private var flushInFlight = false

    /**
     * Primes [synced] from the loaded (already merged) boxes and starts
     * observing the model. Call on the EDT, after the initial
     * `model.setAll` — attaching after seeding is what stops the load from
     * echoing straight back to the server.
     */
    fun seed(loaded: List<BoundingBox>) {
        for (box in loaded) {
            synced[box.id] = box
        }
        model.addListener(object : BoundingBoxModel.Listener {
            override fun boxesChanged() = scheduleFlush(FLUSH_DELAY_MS)
        })
    }

    private fun scheduleFlush(delayMs: Int) {
        if (alarm.isDisposed) {
            return
        }
        alarm.cancelAllRequests()
        alarm.addRequest(::flush, delayMs)
    }

    /** The per-box calls a flush must make; empty = in sync. */
    private data class BoxDiff(
        val box: BoundingBox,
        val saveBox: Boolean,
        val saveAnchor: Boolean,
        val deleteAnchor: Boolean,
    )

    private fun diffOf(box: BoundingBox): BoxDiff {
        val last = synced[box.id]
        val geometryChanged = last == null ||
            last.x != box.x || last.y != box.y ||
            last.width != box.width || last.height != box.height ||
            last.label != box.label || last.category != box.category
        val anchorChanged = last == null ||
            last.textStart != box.textStart ||
            last.textEnd != box.textEnd ||
            last.anchorRevid != box.anchorRevid
        return BoxDiff(
            box = box,
            saveBox = geometryChanged,
            saveAnchor = anchorChanged && box.linked,
            deleteAnchor = anchorChanged && !box.linked && last?.linked == true,
        )
    }

    private fun flush() {
        if (flushInFlight) {
            scheduleFlush(FLUSH_DELAY_MS)
            return
        }
        val current = model.boxes().associateBy { it.id }
        val diffs = current.values.map(::diffOf)
            .filter { it.saveBox || it.saveAnchor || it.deleteAnchor }
        val deletes = synced.keys.filter { it !in current }
        if (diffs.isEmpty() && deletes.isEmpty()) {
            return
        }
        flushInFlight = true
        val backend = WtVfsService.instance.backend
        ApplicationManager.getApplication().executeOnPooledThread {
            val acked = ArrayList<BoundingBox>()
            val deleted = ArrayList<String>()
            var failure: Exception? = null
            try {
                for (diff in diffs) {
                    val box = diff.box
                    if (diff.saveBox) {
                        backend.saveAnnotation(
                            path,
                            PageAnnotation(
                                id = box.id,
                                x = box.x,
                                y = box.y,
                                width = box.width,
                                height = box.height,
                                label = box.label,
                                category = box.category?.wire,
                            ),
                        )
                    }
                    if (diff.saveAnchor) {
                        backend.saveTextAnchor(
                            path,
                            PageTextAnchor(
                                annotationId = box.id,
                                textStart = box.textStart!!,
                                textEnd = box.textEnd!!,
                                anchorRevid = box.anchorRevid,
                            ),
                        )
                    }
                    if (diff.deleteAnchor) {
                        backend.deleteTextAnchor(path, box.id)
                    }
                    acked += box
                }
                for (id in deletes) {
                    backend.deleteAnnotation(path, id)
                    deleted += id
                }
            } catch (e: Exception) {
                failure = e
            }
            ApplicationManager.getApplication().invokeLater {
                flushInFlight = false
                for (box in acked) {
                    synced[box.id] = box
                }
                for (id in deleted) {
                    synced.remove(id)
                }
                if (failure != null) {
                    SYNC_LOG.warn("annotation sync to $path failed, will retry", failure)
                    scheduleFlush(RETRY_DELAY_MS)
                } else {
                    // Catch edits made while the flush was in flight.
                    scheduleFlush(FLUSH_DELAY_MS)
                }
            }
        }
    }

    override fun dispose() {
        // Push whatever is still dirty; the alarm itself dies with this
        // Disposable, so this is the last chance.
        if (!flushInFlight) {
            flush()
        }
    }

    private companion object {
        const val FLUSH_DELAY_MS = 700
        const val RETRY_DELAY_MS = 5_000
    }
}
