package org.limepepper.wikisource.remote.rpc

import com.intellij.openapi.components.Service
import com.intellij.openapi.components.service
import org.limepepper.lang.wikitext.vfs.backend.OcrRunRequest
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.util.Base64

@Service(Service.Level.APP)
class WtRemotePageRpcServiceImpl : WtRemotePageRpcService {

    override suspend fun fetchPage(id: PageIdentifier): PageSnapshot {
        val backend = WtVfsService.instance.backend
        val path = "/${id.wikiId}/${id.title}/@wikitext"
        val payload = try {
            backend.readContent(path).decodeText()
        } catch (e: Exception) {
            ""
        }
        return PageSnapshot(
            id = id,
            content = payload,
            quality = null,
            scanImageUrl = null
        )
    }

    override suspend fun savePage(id: PageIdentifier, content: String, summary: String): Boolean {
        val backend = WtVfsService.instance.backend
        val path = "/${id.wikiId}/${id.title}/@wikitext"
        val base64 = Base64.getEncoder().encodeToString(content.toByteArray(Charsets.UTF_8))
        return try {
            val result = backend.writeContent(path, base64, id.revisionId, summary)
            result.status == org.limepepper.lang.wikitext.vfs.backend.WriteStatus.ok
        } catch (e: Exception) {
            false
        }
    }

    override suspend fun runOcr(request: OcrRequest): OcrResponse {
        val backend = WtVfsService.instance.backend
        val path = "/${request.pageId.wikiId}/${request.pageId.title}"
        val ocrReq = OcrRunRequest(
            engine = request.engine,
            boxX = request.boundingBox?.getOrNull(0),
            boxY = request.boundingBox?.getOrNull(1),
            boxWidth = request.boundingBox?.getOrNull(2),
            boxHeight = request.boundingBox?.getOrNull(3)
        )
        val text = try {
            backend.runOcr(path, ocrReq).decodeText()
        } catch (e: Exception) {
            ""
        }
        return OcrResponse(
            pageId = request.pageId,
            recognizedText = text,
            confidence = 1.0
        )
    }

    companion object {
        fun getInstance(): WtRemotePageRpcService = service<WtRemotePageRpcServiceImpl>()
    }
}
