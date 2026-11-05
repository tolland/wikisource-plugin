package org.limepepper.lang.wikitext.annotation

/**
 * The set of bounding boxes on one image, plus the selection — the mutable
 * state shared between the canvas and whatever persists/links the boxes.
 * Plain Kotlin (no Swing/IntelliJ), so it can be driven from tests and,
 * later, loaded from / saved to the sidecar without touching the canvas.
 *
 * Not thread-safe: mutate on the EDT (or a single owner thread), like the
 * Swing components observing it.
 */
class BoundingBoxModel {
    interface Listener {
        fun boxesChanged() {}

        fun selectionChanged() {}
    }

    private val boxes = LinkedHashMap<String, BoundingBox>()
    private val listeners = mutableListOf<Listener>()

    var selectedId: String? = null
        private set

    val selected: BoundingBox? get() = selectedId?.let(boxes::get)

    fun boxes(): List<BoundingBox> = boxes.values.toList()

    operator fun get(id: String): BoundingBox? = boxes[id]

    fun add(box: BoundingBox) {
        require(box.id !in boxes) { "duplicate box id ${box.id}" }
        boxes[box.id] = box
        fireBoxesChanged()
    }

    /** Replaces the box with [box]'s id; geometry edits go through here. */
    fun update(box: BoundingBox) {
        require(box.id in boxes) { "unknown box id ${box.id}" }
        boxes[box.id] = box
        fireBoxesChanged()
    }

    fun remove(id: String) {
        if (boxes.remove(id) != null) {
            if (selectedId == id) {
                select(null)
            }
            fireBoxesChanged()
        }
    }

    /** Wholesale replacement, e.g. (re)loading persisted boxes. */
    fun setAll(all: List<BoundingBox>) {
        boxes.clear()
        all.forEach { boxes[it.id] = it }
        if (selectedId != null && selectedId !in boxes) {
            selectedId = null
            fireSelectionChanged()
        }
        fireBoxesChanged()
    }

    fun select(id: String?) {
        require(id == null || id in boxes) { "unknown box id $id" }
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

    private fun fireBoxesChanged() = listeners.toList().forEach { it.boxesChanged() }

    private fun fireSelectionChanged() = listeners.toList().forEach { it.selectionChanged() }
}
