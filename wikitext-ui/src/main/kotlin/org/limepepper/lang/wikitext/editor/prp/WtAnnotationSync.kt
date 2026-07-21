package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.util.Alarm
import org.limepepper.lang.wikitext.annotation.BoundingBox
import org.limepepper.lang.wikitext.annotation.BoundingBoxModel
import org.limepepper.lang.wikitext.vfs.backend.PageAnnotation
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService

private val SYNC_LOG = logger<WtAnnotationSync>()

/**
 * Write-behind persistence for the reference pane's [BoundingBoxModel]:
 * observes the model, debounces the change storm a drag produces, and
 * pushes the net difference to the sidecar's `/pages/annotations`. Failures
 * keep the difference dirty and retry, so a briefly-down sidecar loses
 * nothing (short of closing the editor mid-outage).
 *
 * The box is scan geometry only (position, label, category); the
 * transcription text ranges it may correspond to are a wholly independent
 * resource persisted by [WtTextRangeSync]. Deleting a box still drops any
 * text anchor that shares its id server-side, so a stale anchor never
 * outlives its box.
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

    private fun changed(box: BoundingBox): Boolean {
        val last = synced[box.id] ?: return true
        return last.x != box.x || last.y != box.y ||
            last.width != box.width || last.height != box.height ||
            last.label != box.label || last.category != box.category
    }

    private fun flush() {
        if (flushInFlight) {
            scheduleFlush(FLUSH_DELAY_MS)
            return
        }
        val current = model.boxes().associateBy { it.id }
        val saves = current.values.filter(::changed)
        val deletes = synced.keys.filter { it !in current }
        if (saves.isEmpty() && deletes.isEmpty()) {
            return
        }
        flushInFlight = true
        val backend = WtVfsService.instance.backend
        ApplicationManager.getApplication().executeOnPooledThread {
            val acked = ArrayList<BoundingBox>()
            val deleted = ArrayList<String>()
            var failure: Exception? = null
            try {
                for (box in saves) {
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
