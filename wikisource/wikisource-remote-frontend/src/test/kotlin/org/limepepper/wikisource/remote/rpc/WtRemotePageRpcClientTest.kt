package org.limepepper.wikisource.remote.rpc

import org.junit.Assert.assertNull
import org.junit.Test

class WtRemotePageRpcClientTest {

    @Test
    fun testRpcClientSafeFallback() {
        val service = WtRemotePageRpcClient.getService()
        assertNull(service)
    }
}
