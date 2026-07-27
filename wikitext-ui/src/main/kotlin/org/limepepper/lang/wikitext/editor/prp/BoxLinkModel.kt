package org.limepepper.lang.wikitext.editor.prp

/**
 * The box→range links on one page: which bounding box's content is destined
 * for which [TextRange] — the mutable state shared between the canvas chrome
 * (link glyphs, popup menu), the editor, and the write-behind persistence
 * ([WtBoxLinkSync]). Deliberately plain Kotlin, like [TextRangeModel] and
 * [org.limepepper.lang.wikitext.annotation.BoundingBoxModel], so it can be
 * driven from tests.
 *
 * A box links to at most one range; several boxes may target one range. A
 * link is only meaningful while both endpoints exist, so the host prunes via
 * [retainRanges]/[retainBoxes] when either side's set changes — a pruned
 * link is an ordinary removal that the sync then deletes server-side.
 *
 * Not thread-safe: mutate on the EDT (or a single owner thread), like the
 * components observing it.
 */
class BoxLinkModel {
    interface Listener {
        fun linksChanged() {}
    }

    private val links = LinkedHashMap<String, String>() // boxId → rangeId
    private val listeners = mutableListOf<Listener>()

    fun links(): Map<String, String> = LinkedHashMap(links)

    fun rangeFor(boxId: String): String? = links[boxId]

    fun boxesFor(rangeId: String): List<String> =
        links.filterValues { it == rangeId }.keys.toList()

    fun isLinked(boxId: String): Boolean = boxId in links

    fun link(boxId: String, rangeId: String) {
        if (links[boxId] != rangeId) {
            links[boxId] = rangeId
            fireLinksChanged()
        }
    }

    fun unlink(boxId: String) {
        if (links.remove(boxId) != null) {
            fireLinksChanged()
        }
    }

    /** Wholesale replacement, e.g. (re)loading persisted links. */
    fun setAll(all: Map<String, String>) {
        links.clear()
        links.putAll(all)
        fireLinksChanged()
    }

    /** Drops links whose target range is gone (deleted or replaced). */
    fun retainRanges(validRangeIds: Set<String>) {
        if (links.values.removeIf { it !in validRangeIds }) {
            fireLinksChanged()
        }
    }

    /** Drops links whose box is gone. */
    fun retainBoxes(validBoxIds: Set<String>) {
        if (links.keys.removeIf { it !in validBoxIds }) {
            fireLinksChanged()
        }
    }

    fun addListener(listener: Listener) {
        listeners += listener
    }

    fun removeListener(listener: Listener) {
        listeners -= listener
    }

    private fun fireLinksChanged() = listeners.toList().forEach { it.linksChanged() }
}
