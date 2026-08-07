package org.limepepper.lang.wikitext.vfs.backend

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.Service

/**
 * Application-level service that owns the [VfsBackend] singleton.
 *
 * Registered in wikisource.wikitext-vfs.xml as an applicationService.
 * Retrieve via [WtVfsService.instance].
 *
 * The base URL is hard-coded to the dev-convention wtbot port (18564, see
 * docs/logging.md) for now; a persistent settings component can inject it
 * later.
 */
@Service(Service.Level.APP)
class WtVfsService {

    val backend: VfsBackend = HttpVfsBackend(baseUrl = "http://127.0.100.1:18564")

    companion object {
        @JvmStatic
        val instance: WtVfsService
            get() = ApplicationManager.getApplication().getService(WtVfsService::class.java)
    }
}
