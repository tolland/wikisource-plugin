package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.util.Alarm
import org.limepepper.lang.wikitext.vfs.backend.PageBoxLink
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService

private val SYNC_LOG = logger<WtBoxLinkSync>()

/**
 * Write-behind persistence for a [BoxLinkModel]: observes the model,
 * debounces, and pushes the net difference to the sidecar's
 * `/pages/box-links` — the same shape as [WtTextRangeSync] /
 * [WtAnnotationSync]. Failures keep the difference dirty and retry.
 *
 * One wrinkle links have that the other resources don't: the server prunes
 * links itself when a box or range is deleted, so a client-side delete may
 * find the row already gone — an HTTP 404 on delete is success, not a
 * failure to retry. Likewise a save may race a range deletion (404 because
 * the target range vanished); the model prune that follows will retract the
 * link, so that save is dropped rather than retried.
 *
 * EDT discipline: the model is EDT-owned, so diffing happens on the EDT (via
 * [alarm]) and only the HTTP calls hop to a pooled thread.
 */
class WtBoxLinkSync(
    private val model: BoxLinkModel,
    private val path: String,
) : Disposable {
    /** Last state the server acknowledged: boxId → rangeId. */
    private val synced = HashMap<String, String>()

    private val alarm = Alarm(Alarm.ThreadToUse.SWING_THREAD, this)
    private var flushInFlight = false

    /**
     * Primes [synced] from the loaded links and starts observing the model.
     * Call on the EDT, after the initial `model.setAll` — attaching after
     * seeding is what stops the load from echoing straight back to the server.
     */
    fun seed(loaded: Map<String, String>) {
        synced.putAll(loaded)
        model.addListener(object : BoxLinkModel.Listener {
            override fun linksChanged() = scheduleFlush(FLUSH_DELAY_MS)
        })
        // Seed with the *server* state even when the host pruned some links
        // on load (range gone); this first flush pushes those deletions.
        scheduleFlush(FLUSH_DELAY_MS)
    }

    private fun scheduleFlush(delayMs: Int) {
        if (alarm.isDisposed) {
            return
        }
        alarm.cancelAllRequests()
        alarm.addRequest(::flush, delayMs)
    }

    private fun flush() {
        if (flushInFlight) {
            scheduleFlush(FLUSH_DELAY_MS)
            return
        }
        val current = model.links()
        val saves = current.filter { (boxId, rangeId) -> synced[boxId] != rangeId }
        val deletes = synced.keys.filter { it !in current }
        if (saves.isEmpty() && deletes.isEmpty()) {
            return
        }
        flushInFlight = true
        val backend = WtVfsService.instance.backend
        ApplicationManager.getApplication().executeOnPooledThread {
            val acked = HashMap<String, String>()
            val dropped = ArrayList<Pair<String, String>>()
            val deleted = ArrayList<String>()
            var failure: Exception? = null
            try {
                for ((boxId, rangeId) in saves) {
                    try {
                        backend.saveBoxLink(path, PageBoxLink(boxId = boxId, rangeId = rangeId))
                        acked[boxId] = rangeId
                    } catch (e: VfsBackendException) {
                        if (e.statusCode != 404) throw e
                        // The target range vanished under us; the prune that
                        // follows retracts the link, so don't retry the save.
                        dropped += boxId to rangeId
                    }
                }
                for (boxId in deletes) {
                    try {
                        backend.deleteBoxLink(path, boxId)
                    } catch (e: VfsBackendException) {
                        if (e.statusCode != 404) throw e // already pruned server-side
                    }
                    deleted += boxId
                }
            } catch (e: Exception) {
                failure = e
            }
            ApplicationManager.getApplication().invokeLater {
                flushInFlight = false
                synced.putAll(acked)
                for (boxId in deleted) {
                    synced.remove(boxId)
                }
                for ((boxId, rangeId) in dropped) {
                    synced.remove(boxId)
                    // Only retract if the model still holds the doomed link —
                    // a re-link to another range made meanwhile stays.
                    if (model.rangeFor(boxId) == rangeId) {
                        model.unlink(boxId)
                    }
                }
                if (failure != null) {
                    SYNC_LOG.warn("box-link sync to $path failed, will retry", failure)
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
