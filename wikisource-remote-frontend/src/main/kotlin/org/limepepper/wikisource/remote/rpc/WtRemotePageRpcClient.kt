package org.limepepper.wikisource.remote.rpc

import com.intellij.openapi.application.ApplicationManager

object WtRemotePageRpcClient {
    fun getService(): WtRemotePageRpcService? {
        val app = ApplicationManager.getApplication() ?: return null
        return app.getService(WtRemotePageRpcService::class.java)
    }
}
