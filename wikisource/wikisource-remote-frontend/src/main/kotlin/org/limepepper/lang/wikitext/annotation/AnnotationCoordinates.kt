package org.limepepper.lang.wikitext.annotation

import org.limepepper.lang.wikitext.vfs.backend.PageAnnotation

/** The canvas uses decoded-image pixels; persistence uses fractions of the full page. */
fun PageAnnotation.toPixelBox(imageWidth: Int, imageHeight: Int): BoundingBox {
    require(imageWidth > 0 && imageHeight > 0)
    return BoundingBox(
        id = id,
        x = x * imageWidth,
        y = y * imageHeight,
        width = width * imageWidth,
        height = height * imageHeight,
        label = label,
        category = AnnotationCategory.fromWire(category) ?: AnnotationCategory.UNKNOWN,
    )
}

fun BoundingBox.toNormalizedAnnotation(imageWidth: Int, imageHeight: Int): PageAnnotation {
    require(imageWidth > 0 && imageHeight > 0)
    return PageAnnotation(
        id = id,
        x = x / imageWidth,
        y = y / imageHeight,
        width = width / imageWidth,
        height = height / imageHeight,
        label = label,
        category = category.wire,
    )
}
