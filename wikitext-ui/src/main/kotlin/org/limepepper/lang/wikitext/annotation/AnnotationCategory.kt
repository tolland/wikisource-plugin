package org.limepepper.lang.wikitext.annotation

/**
 * What a scan region means to the OCR pipeline — mirrors the sidecar's
 * `AnnotationCategory` enum ([wire] is the JSON value). When page images are
 * cut into subsections and sent to OCR, the category decides what a box
 * contributes: [BODY]/[PARAGRAPH]/[SECTION] regions are transcribed,
 * [HEADER]/[FOOTER] route to the page header/footer fields, [IGNORE] is
 * skipped. [EQUATION] is is sent to a "Tex" specific OCR backend.
 */
enum class AnnotationCategory(val wire: String, val displayName: String) {
    HEADER("header", "Header"),
    FOOTER("footer", "Footer"),
    BODY("body", "Body"),
    PARAGRAPH("paragraph", "Paragraph"),
    SECTION("section", "Section"),
    IGNORE("ignore", "Ignore"),
    EQUATION("equation", "equation"),
    ;

    companion object {
        /** Null for null or an unrecognized wire value (a newer sidecar). */
        fun fromWire(value: String?): AnnotationCategory? =
            entries.firstOrNull { it.wire == value }
    }
}
