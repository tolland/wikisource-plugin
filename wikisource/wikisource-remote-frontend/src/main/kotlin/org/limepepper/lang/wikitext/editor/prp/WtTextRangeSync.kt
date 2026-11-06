package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.util.Alarm
import org.limepepper.lang.wikitext.vfs.backend.PageTextAnchor
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService

private val SYNC_LOG = logger<WtTextRangeSync>()

/**
 * Write-behind persistence for a [TextRangeModel]: observes the model,
 * debounces the change storm a drag produces, and pushes the net difference to
 * the sidecar's `/pages/text-anchors`. Failures keep the difference dirty and
 * retry, so a briefly-down sidecar loses nothing (short of closing the editor
 * mid-outage). A direct analogue of
 * [org.limepepper.lang.wikitext.editor.prp.WtAnnotationSync], but for a single
 * resource (text anchors are their own endpoint, keyed by range id) rather
 * than the box's split geometry/anchor pair.
 *
 * EDT discipline: the model is EDT-owned, so diffing happens on the EDT (via
 * [alarm]) and only the HTTP calls hop to a pooled thread.
 */
class WtTextRangeSync(
    private val model: TextRangeModel,
    private val path: String,
) : Disposable {
    /** Last state the server acknowledged, by range id. */
    private val synced = HashMap<String, TextRange>()

    private val alarm = Alarm(Alarm.ThreadToUse.SWING_THREAD, this)
    private var flushInFlight = false

    /**
     * Primes [synced] from the loaded ranges and starts observing the model.
     * Call on the EDT, after the initial `model.setAll` — attaching after
     * seeding is what stops the load from echoing straight back to the server.
     */
    fun seed(loaded: List<TextRange>) {
        for (range in loaded) {
            synced[range.id] = range
        }
        model.addListener(object : TextRangeModel.Listener {
            override fun rangesChanged() = scheduleFlush(FLUSH_DELAY_MS)
        })
    }

    private fun scheduleFlush(delayMs: Int) {
        if (alarm.isDisposed) {
            return
        }
        alarm.cancelAllRequests()
        alarm.addRequest(::flush, delayMs)
    }

    private fun changed(range: TextRange): Boolean {
        val last = synced[range.id] ?: return true
        return last.start != range.start || last.end != range.end || last.anchorRevid != range.anchorRevid
    }

    private fun flush() {
        if (flushInFlight) {
            scheduleFlush(FLUSH_DELAY_MS)
            return
        }
        val current = model.ranges().associateBy { it.id }
        val saves = current.values.filter(::changed)
        val deletes = synced.keys.filter { it !in current }
        if (saves.isEmpty() && deletes.isEmpty()) {
            return
        }
        flushInFlight = true
        val backend = WtVfsService.instance.backend
        ApplicationManager.getApplication().executeOnPooledThread {
            val acked = ArrayList<TextRange>()
            val deleted = ArrayList<String>()
            var failure: Exception? = null
            try {
                for (range in saves) {
                    backend.saveTextAnchor(
                        path,
                        PageTextAnchor(
                            annotationId = range.id,
                            textStart = range.start,
                            textEnd = range.end,
                            anchorRevid = range.anchorRevid,
                        ),
                    )
                    acked += range
                }
                for (id in deletes) {
                    backend.deleteTextAnchor(path, id)
                    deleted += id
                }
            } catch (e: Exception) {
                failure = e
            }
            ApplicationManager.getApplication().invokeLater {
                flushInFlight = false
                for (range in acked) {
                    synced[range.id] = range
                }
                for (id in deleted) {
                    synced.remove(id)
                }
                if (failure != null) {
                    SYNC_LOG.warn("text-range sync to $path failed, will retry", failure)
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
