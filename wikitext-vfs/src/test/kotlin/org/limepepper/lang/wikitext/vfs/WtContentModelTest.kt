package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.fileTypes.PlainTextFileType
import org.junit.Assert.assertEquals
import org.junit.Test
import org.limepepper.lang.wikitext.WtFileType

class WtContentModelTest {

    @Test fun `wikitext-flavored content models map to WtFileType`() {
        for (id in listOf("proofread-index", "proofread-page", "wikitext")) {
            assertEquals(id, WtFileType, WtContentModel.fileTypeFor(id))
        }
    }

    @Test fun `non-wikitext content models map to plain text, not WtFileType`() {
        for (id in listOf("sanitized-css", "json")) {
            assertEquals(id, PlainTextFileType.INSTANCE, WtContentModel.fileTypeFor(id))
        }
    }

    @Test fun `null or unrecognized content model defaults to WtFileType`() {
        assertEquals(WtFileType, WtContentModel.fileTypeFor(null))
        assertEquals(WtFileType, WtContentModel.fileTypeFor("some-future-content-model"))
    }
}
