package org.limepepper.lang.wikitext.vfs

/**
 * The `wikisource://` path grammar, client side:
 *
 *     /{family}/{code}/{namespace}/{title segments...}[/@{aspect}]
 *
 * A title is a node (a directory); an *aspect* is one view of it — its
 * wikitext, its properties — and is the file you open. The server is the
 * authority on what exists; this only splits strings, so the UI can tell
 * aspect files from title nodes without a round trip.
 *
 * A title segment that itself starts with `@` or `%` is escaped (`%40`,
 * `%25`), so a trailing `@name` is always an aspect.
 */
object WtPaths {
    const val ASPECT_PREFIX: String = "@"
    const val WIKITEXT: String = "wikitext"
    const val PROPS: String = "props"
    const val PAGES: String = "pages"

    private const val FIRST_TITLE_SEGMENT = 3
    private const val PAGE_NAMESPACE = "Page"

    /** The trailing `@aspect` of [path], or null for a title node. */
    fun aspectOf(path: String): String? {
        val segments = path.trim('/').split('/')
        if (segments.size <= FIRST_TITLE_SEGMENT) return null
        val last = segments.last()
        return if (last.startsWith(ASPECT_PREFIX) && last.length > 1) last.substring(1) else null
    }

    /** The path of the title node [path] addresses or belongs to. */
    fun nodePath(path: String): String {
        val aspect = aspectOf(path) ?: return path
        return path.trimEnd('/').removeSuffix("/$ASPECT_PREFIX$aspect")
    }

    /** The path of [aspect] of the title node at [nodePath]. */
    fun aspectPath(nodePath: String, aspect: String): String =
        "${nodePath.trimEnd('/')}/$ASPECT_PREFIX$aspect"

    /** Undoes the leading-character escape of one title segment. */
    fun decodeSegment(segment: String): String = when {
        segment.startsWith("%40") -> "@" + segment.substring(3)
        segment.startsWith("%25") -> "%" + segment.substring(3)
        else -> segment
    }

    /**
     * A short, human name for the title a path addresses — what an editor tab
     * or tree label should say. The last title segment, except in the Page
     * namespace where one scan page is `Book.djvu/171`, which reads as
     * itself. Non-default aspects are named: `Chapter 1 (@props)`.
     */
    fun displayName(path: String): String {
        val segments = path.trim('/').split('/')
        if (segments.size <= FIRST_TITLE_SEGMENT) return segments.lastOrNull().orEmpty()
        val aspect = aspectOf(path)
        val titleSegments = segments
            .drop(FIRST_TITLE_SEGMENT)
            .let { if (aspect != null) it.dropLast(1) else it }
            .map(::decodeSegment)
        val title = if (segments[FIRST_TITLE_SEGMENT - 1] == PAGE_NAMESPACE) {
            titleSegments.joinToString("/")
        } else {
            titleSegments.lastOrNull().orEmpty()
        }
        return if (aspect == null || aspect == WIKITEXT) title else "$title ($ASPECT_PREFIX$aspect)"
    }
}
