package org.limepepper.lang.wikitext.annotation

import org.junit.Test
import org.limepepper.lang.wikitext.vfs.backend.PageAnnotation
import kotlin.test.assertEquals

class AnnotationCoordinatesTest {
    @Test fun `same persisted region scales with both image dimensions`() {
        val annotation = PageAnnotation("box", 0.1, 0.2, 0.3, 0.4, "equation", "equation")
        val small = annotation.toPixelBox(500, 800)
        val large = annotation.toPixelBox(2000, 3200)
        assertEquals(50.0, small.x)
        assertEquals(160.0, small.y)
        assertEquals(600.0, large.width)
        assertEquals(1280.0, large.height)
        assertEquals(annotation, small.toNormalizedAnnotation(500, 800))
        assertEquals(annotation, large.toNormalizedAnnotation(2000, 3200))
    }

    @Test fun `missing or unrecognized category loads as unknown`() {
        for (wire in listOf(null, "unknown", "marginalia")) {
            val box = PageAnnotation("box", 0.1, 0.2, 0.3, 0.4, null, wire).toPixelBox(100, 100)
            assertEquals(AnnotationCategory.UNKNOWN, box.category)
        }
    }
}
