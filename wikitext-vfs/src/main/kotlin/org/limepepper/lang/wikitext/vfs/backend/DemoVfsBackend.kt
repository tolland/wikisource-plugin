package org.limepepper.lang.wikitext.vfs.backend

/**
 * Seeded in-memory backend selected by `-Dwtbot.fakeBackend=demo` (see
 * [WtVfsService]). It exists so a real IDE can be launched, and driven by the
 * `wikitext-ide-tests` module, without a wtbot sidecar or a wiki.
 */
object DemoVfsBackend {

    /** System property that makes [WtVfsService] use [create] instead of `HttpVfsBackend`. */
    const val PROPERTY: String = "wtbot.fakeBackend"

    const val SITE: String = "/wikisource/en"
    const val MAIN_PAGE: String = "$SITE/Book/Demo"
    const val MAIN_PAGE_WIKITEXT: String = "$MAIN_PAGE/@wikitext"

    fun create(): FakeVfsBackend = FakeVfsBackend()
        .addDirectory(SITE)
        .addDirectory("$SITE/Book")
        .addDirectory(MAIN_PAGE, aspects = listOf("wikitext", "props"))
        .addFile(
            MAIN_PAGE_WIKITEXT,
            "== Demo ==\nSome '''bold''' text and a [[link]].\n",
            name = "@wikitext",
            revid = 1,
        )
}
