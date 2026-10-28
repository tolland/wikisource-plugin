package org.limepepper.lang.wikitext.vfs

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class WtPathsTest {

    @Test fun `trailing at-segment is the aspect`() {
        assertEquals("props", WtPaths.aspectOf("/wikisource/en/Book/Virtues and vices/Ch 1/@props"))
        assertEquals("wikitext", WtPaths.aspectOf("/wikisource/en/Index/Foo.djvu/@wikitext"))
    }

    @Test fun `title nodes and containers have no aspect`() {
        assertNull(WtPaths.aspectOf("/"))
        assertNull(WtPaths.aspectOf("/wikisource/en"))
        assertNull(WtPaths.aspectOf("/wikisource/en/Book"))
        assertNull(WtPaths.aspectOf("/wikisource/en/Book/Virtues and vices"))
        // an aspect needs a title before it
        assertNull(WtPaths.aspectOf("/wikisource/en/@x"))
        // an escaped leading @ is a title segment, not an aspect
        assertNull(WtPaths.aspectOf("/wikisource/en/(Main)/%40home"))
    }

    @Test fun `node path strips the aspect`() {
        assertEquals(
            "/wikisource/en/Book/Foo",
            WtPaths.nodePath("/wikisource/en/Book/Foo/@wikitext"),
        )
        assertEquals("/wikisource/en/Book/Foo", WtPaths.nodePath("/wikisource/en/Book/Foo"))
    }

    @Test fun `aspect path appends the aspect`() {
        assertEquals(
            "/wikisource/en/Book/Foo/@props",
            WtPaths.aspectPath("/wikisource/en/Book/Foo/", WtPaths.PROPS),
        )
    }

    @Test fun `display name names the title, not the aspect segment`() {
        assertEquals("Foo", WtPaths.displayName("/wikisource/en/Book/Foo/@wikitext"))
        assertEquals("Ch 1", WtPaths.displayName("/wikisource/en/Book/Foo/Ch 1"))
        assertEquals("Foo (@props)", WtPaths.displayName("/wikisource/en/Book/Foo/@props"))
        assertEquals("@home", WtPaths.displayName("/wikisource/en/(Main)/%40home/@wikitext"))
    }

    @Test fun `a scanned page reads as book and number`() {
        assertEquals(
            "Foo.djvu/171",
            WtPaths.displayName("/wikisource/en/Page/Foo.djvu/171/@wikitext"),
        )
    }

    @Test fun `short paths keep their last segment`() {
        assertEquals("en", WtPaths.displayName("/wikisource/en"))
        assertEquals("", WtPaths.displayName("/"))
    }
}
