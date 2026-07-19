package org.limepepper.lang.wikitext.vfs

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import org.limepepper.lang.wikitext.PrpFileType
import org.limepepper.lang.wikitext.WtFileType

class WtContentModelTest {

    @Test fun `wikitext-flavored content models map to WtFileType`() {
        for (id in listOf("proofread-index", "wikitext")) {
            assertEquals(id, WtFileType, WtContentModel.fileTypeFor(id))
        }
        for (id in listOf("proofread-page" )) {
            assertEquals(id, PrpFileType, WtContentModel.fileTypeFor(id))
        }
    }

    @Test fun `non-wikitext content models do not map to WtFileType`() {
        // The exact FileType (real CSS/JSON vs a platform fallback) depends on
        // which file-type plugins are loaded in the running IDE, via
        // FileTypeRegistry -- not resolvable from a bare JUnit test. What must
        // hold everywhere is that these never get parsed as wikitext.
        for (id in listOf("sanitized-css", "json")) {
            assertNotEquals(id, WtFileType, WtContentModel.fileTypeFor(id))
        }
    }

    @Test fun `null or unrecognized content model defaults to WtFileType`() {
        assertEquals(WtFileType, WtContentModel.fileTypeFor(null))
        assertEquals(WtFileType, WtContentModel.fileTypeFor("some-future-content-model"))
    }
}
