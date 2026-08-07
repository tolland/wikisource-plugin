package org.limepepper.lang.wikitext.vfs.settings

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.Service.Level
import com.intellij.openapi.diagnostic.Logger
import com.intellij.openapi.project.Project
import org.limepepper.lang.wikitext.vfs.backend.OcrBackendInfo
import org.limepepper.lang.wikitext.vfs.backend.OcrCatalog
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.util.concurrent.atomic.AtomicReference

/**
 * Remembers what the sidecar last said an OCR backend offers, so the
 * favourites settings page has real engines and languages to pick from.
 *
 * Discovery needs a page path (the sidecar resolves the site, and its
 * backends, from the page) but the settings dialog has no page open — so
 * rather than making the dialog find one, editors publish what they
 * discovered here as they open, and the dialog reads the latest. That
 * makes the picker best-effort by construction: with nothing discovered
 * yet the settings page falls back to free text, which still produces a
 * working favourite. The sidecar does the real caching (see
 * ocrapi.catalog); this is only a UI-side handoff between two places that
 * never meet.
 */
@Service(Level.PROJECT)
class OcrCatalogService(private val project: Project) {

    private val catalog = AtomicReference(OcrCatalog.EMPTY)
    private val backends = AtomicReference<List<OcrBackendInfo>>(emptyList())

    /** The most recently discovered catalog; [OcrCatalog.EMPTY] until one is. */
    fun cachedCatalog(): OcrCatalog = catalog.get()

    /** The most recently discovered backend list; empty until one is. */
    fun cachedBackends(): List<OcrBackendInfo> = backends.get()

    /** Every engine name seen, for the settings page's engine picker. */
    fun knownEngines(): List<String> = catalog.get().engines.map { it.engine }

    /**
     * Forgets what was discovered, for when the VFS is switched to a different
     * sidecar: OCR backends are configured per site on the sidecar, so the old
     * one's engines and languages say nothing about the new one's. The picker
     * falls back to free text until an editor rediscovers.
     */
    fun clearCache() {
        catalog.set(OcrCatalog.EMPTY)
        backends.set(emptyList())
    }

    /**
     * Blocking discovery for [path], publishing the result for the settings
     * page. Returns what it found so a caller that needs it now (an editor
     * building its menu) does not have to read it back. Call off the EDT.
     */
    fun discover(path: String): Pair<List<OcrBackendInfo>, OcrCatalog> {
        val backend = WtVfsService.instance.backend
        val found = try {
            backend.listOcrBackends(path)
        } catch (e: Exception) {
            LOG.warn("OCR backend discovery failed for $path", e)
            emptyList()
        }
        backends.set(found)

        // Only URL-driven backends can be introspected; asking a token_api
        // backend costs a round trip to learn nothing.
        val discoverable = found.firstOrNull { it.supportsDiscovery }
        val models = if (discoverable == null) {
            OcrCatalog.EMPTY
        } else {
            try {
                backend.listOcrModels(path, discoverable.name)
            } catch (e: Exception) {
                LOG.warn("OCR model discovery failed for $path", e)
                OcrCatalog.EMPTY
            }
        }
        if (models.engines.isNotEmpty()) {
            catalog.set(models)
        } else if (models.error != null) {
            LOG.info("OCR model discovery for $path reported: ${models.error}")
        }
        return found to models
    }

    /** Fire-and-forget [discover], for callers on the EDT. */
    fun discoverAsync(path: String, onDone: (List<OcrBackendInfo>, OcrCatalog) -> Unit = { _, _ -> }) {
        ApplicationManager.getApplication().executeOnPooledThread {
            val (found, models) = discover(path)
            onDone(found, models)
        }
    }

    companion object {
        private val LOG = Logger.getInstance(OcrCatalogService::class.java)

        fun getInstance(project: Project): OcrCatalogService =
            project.getService(OcrCatalogService::class.java)
    }
}
