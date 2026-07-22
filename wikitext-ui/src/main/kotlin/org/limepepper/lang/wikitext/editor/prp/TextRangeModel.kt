package org.limepepper.lang.wikitext.editor.prp

/**
 * The set of [TextRange]s on one page plus the selection — the mutable state
 * shared between the editor chrome ([WtTextRangeManager]) and the write-behind
 * persistence ([WtTextRangeSync]). Deliberately plain Kotlin (no Swing /
 * IntelliJ types) so it can be driven from tests, and a direct analogue of
 * [org.limepepper.lang.wikitext.annotation.BoundingBoxModel] on the scan side.
 *
 * Not thread-safe: mutate on the EDT (or a single owner thread), like the
 * editor components observing it.
 */
class TextRangeModel {
    interface Listener {
        fun rangesChanged() {}

        fun selectionChanged() {}
    }

    private val ranges = LinkedHashMap<String, TextRange>()
    private val listeners = mutableListOf<Listener>()

    var selectedId: String? = null
        private set

    val selected: TextRange? get() = selectedId?.let(ranges::get)

    fun ranges(): List<TextRange> = ranges.values.toList()

    operator fun get(id: String): TextRange? = ranges[id]

    /** Whether [range] is disjoint from every range except itself. */
    fun canPlace(range: TextRange): Boolean = ranges.values.none {
        it.id != range.id && it.conflictsWith(range)
    }

    fun add(range: TextRange) {
        require(range.id !in ranges) { "duplicate range id ${range.id}" }
        require(canPlace(range)) { "text range ${range.start}..${range.end} overlaps an existing range" }
        ranges[range.id] = range
        fireRangesChanged()
    }

    /** Replaces the range with [range]'s id; extent edits go through here. */
    fun update(range: TextRange) {
        require(range.id in ranges) { "unknown range id ${range.id}" }
        require(canPlace(range)) { "text range ${range.start}..${range.end} overlaps an existing range" }
        ranges[range.id] = range
        fireRangesChanged()
    }

    fun remove(id: String) {
        if (ranges.remove(id) != null) {
            if (selectedId == id) {
                select(null)
            }
            fireRangesChanged()
        }
    }

    /** Wholesale replacement, e.g. (re)loading persisted ranges. */
    fun setAll(all: List<TextRange>) {
        require(all.distinctBy { it.id }.size == all.size) { "duplicate range id" }
        require(all.indices.none { left ->
            ((left + 1)..<all.size).any { right -> all[left].conflictsWith(all[right]) }
        }) { "text ranges must not overlap or nest" }
        ranges.clear()
        all.forEach { ranges[it.id] = it }
        if (selectedId != null && selectedId !in ranges) {
            selectedId = null
            fireSelectionChanged()
        }
        fireRangesChanged()
    }

    fun select(id: String?) {
        require(id == null || id in ranges) { "unknown range id $id" }
        if (selectedId != id) {
            selectedId = id
            fireSelectionChanged()
        }
    }

    fun addListener(listener: Listener) {
        listeners += listener
    }

    fun removeListener(listener: Listener) {
        listeners -= listener
    }

    private fun fireRangesChanged() = listeners.toList().forEach { it.rangesChanged() }

    private fun fireSelectionChanged() = listeners.toList().forEach { it.selectionChanged() }
}
