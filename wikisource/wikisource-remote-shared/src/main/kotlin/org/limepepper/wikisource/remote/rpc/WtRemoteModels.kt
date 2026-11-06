package org.limepepper.wikisource.remote.rpc

import kotlinx.serialization.Serializable

@Serializable
data class PageIdentifier(
    val wikiId: String,
    val title: String,
    val revisionId: Long? = null
)

@Serializable
data class PageSnapshot(
    val id: PageIdentifier,
    val content: String,
    val quality: Int? = null,
    val scanImageUrl: String? = null
)

@Serializable
data class OcrRequest(
    val pageId: PageIdentifier,
    val engine: String,
    val boundingBox: List<Double>? = null
)

@Serializable
data class OcrResponse(
    val pageId: PageIdentifier,
    val recognizedText: String,
    val confidence: Double
)

interface WtRemotePageRpcService {
    suspend fun fetchPage(id: PageIdentifier): PageSnapshot
    suspend fun savePage(id: PageIdentifier, content: String, summary: String): Boolean
    suspend fun runOcr(request: OcrRequest): OcrResponse
}
