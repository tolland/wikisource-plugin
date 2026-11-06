package org.limepepper.lang.wikitext.vfs

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import org.limepepper.lang.wikitext.PrpFileType
import org.limepepper.lang.wikitext.WtFileType

class WtContentModelTest {

    @Test fun `wikitext-flavored content models map to wikitext file type`() {
        for (id in listOf("proofread-index", "wikitext")) {
            assertEquals(id, WtFileType, WtContentModel.fileTypeFor(id))
        }
        for (id in listOf("proofread-page")) {
            assertEquals(id, PrpFileType, WtContentModel.fileTypeFor(id))
        }
    }

    @Test fun `non-wikitext content models do not map to wikitext file type`() {
        for (id in listOf("sanitized-css", "json")) {
            assertNotEquals(id, WtFileType, WtContentModel.fileTypeFor(id))
        }
    }

    @Test fun `null or unrecognized content model defaults to wikitext file type`() {
        assertEquals(WtFileType, WtContentModel.fileTypeFor(null))
        assertEquals(WtFileType, WtContentModel.fileTypeFor("some-future-content-model"))
    }
}
