package org.limepepper.lang.wikitext.editing

import com.intellij.openapi.diagnostic.thisLogger
import com.intellij.openapi.util.registry.Registry
import org.limepepper.lang.wikitext.annotation.ImageAnnotationCanvas
import org.limepepper.lang.wikitext.editor.prp.PrpPreviewBrowser

/**
 * Runtime switches for the text-editing features.
 *
 * These are prototypes: the point is to stand up several of the interaction
 * styles the platform offers, live with them, and delete the losers. That only
 * works if each one can be turned off — and swapped for an alternative — from
 * a running IDE rather than by editing `plugin.xml` and restarting. So every
 * such choice is a [Registry] key (Help → Find Action → "Registry…"), declared
 * with a `<registryKey>` entry in `wikisource.wikitext-ui.xml`.
 *
 * Registry rather than a Settings page on purpose: settings are a promise to
 * users that an option is supported, and none of this is yet. When a choice
 * settles, its key should be deleted along with the implementation it was
 * guarding — not promoted to a checkbox by default.
 */
object WtEditingFlags {

    // ---- Surround With ---------------------------------------------------

    /** Master switch for the Surround With contribution. */
    fun surroundEnabled(): Boolean = boolean(SURROUND_ENABLED, true)

    /**
     * Which surround interaction to use. The implementations produce identical
     * markup (both go through
     * [org.limepepper.lang.wikitext.editing.WtWrapRenderer]) and differ only in
     * how the user fills in a tag's variable.
     */
    fun surroundStrategy(): SurroundStrategy =
        SurroundStrategy.byId(string(SURROUND_STRATEGY, SurroundStrategy.TEMPLATE.id))

    /**
     * How a construct needing a value (currently only `<section>`) asks for it.
     * IntelliJ's own habit is an in-editor popup, which is divisive enough to
     * be worth making switchable from the first commit.
     */
    fun variablePromptStyle(): VariablePromptStyle =
        VariablePromptStyle.byId(string(VARIABLE_PROMPT, VariablePromptStyle.INLINE.id))

    /**
     * The competing Surround With implementations.
     *
     * [TEMPLATE] is the platform-idiomatic one — after inserting the markup it
     * starts a live template so the section name is typed straight into the
     * document with both begin/end markers mirroring each other.
     *
     * [DOCUMENT] is the dumb one — a single document edit, with the
     * placeholder left selected. No template state machine, so nothing can get
     * stuck, and it behaves identically whether the file is a real file or a
     * `wikisource://` one. Keep it until [TEMPLATE] has proven itself.
     */
    enum class SurroundStrategy(val id: String) {
        TEMPLATE("template"),
        DOCUMENT("document"),
        ;

        companion object {
            fun byId(id: String): SurroundStrategy =
                entries.firstOrNull { it.id == id } ?: TEMPLATE
        }
    }

    /** How to ask the user for a tag variable's value. */
    enum class VariablePromptStyle(val id: String) {
        /** Type it in the document (live template, or a selected placeholder). */
        INLINE("inline"),

        /** A modal dialog before anything is inserted. */
        DIALOG("dialog"),

        /** Insert the placeholder and ask nothing at all. */
        NONE("none"),
        ;

        companion object {
            fun byId(id: String): VariablePromptStyle =
                entries.firstOrNull { it.id == id } ?: INLINE
        }
    }

    // ---- Formatting toggles (Ctrl+B / Ctrl+I) ----------------------------

    /** Master switch for the bold/italic toggle actions. */
    fun toggleEnabled(): Boolean = boolean(TOGGLE_ENABLED, true)

    /**
     * Whether the toggle actions are promoted over the platform actions that
     * share their shortcuts (Go To Declaration, Implement Methods). Separate
     * from [toggleEnabled] because hijacking two very well-known keystrokes is
     * the part most likely to be regretted — this hands them back without
     * losing the actions themselves from the menu.
     */
    fun togglePromote(): Boolean = boolean(TOGGLE_PROMOTE, true)

    // ---- Proofread preview pane ------------------------------------------

    /**
     * Which preview(s) the ProofreadPage preview pane shows on open — the
     * "compare both" choice from its toolbar. Both by default: proofreading
     * means reading the scan while checking the render against it.
     *
     * Returns the id of a `PrpPreviewBrowser.Mode`; an unrecognised value
     * falls back to showing both rather than failing to open an editor.
     */
    fun previewDefaultMode(): PrpPreviewBrowser.Mode =
        when (string(PREVIEW_MODE, PREVIEW_MODE_BOTH).lowercase()) {
            "image" -> PrpPreviewBrowser.Mode.IMAGE_ONLY
            "render" -> PrpPreviewBrowser.Mode.RENDER_ONLY
            else -> PrpPreviewBrowser.Mode.SPLIT
        }

    /**
     * Whether the two previews are tiled stacked (scan above render) rather
     * than side by side, when both are shown.
     *
     * Note these are *defaults*, not persisted preferences — nothing stores
     * the pane's mode or orientation across sessions, so they apply on every
     * open and a toolbar change lasts only for that editor's lifetime.
     */
    fun previewSplitStacked(): Boolean = boolean(PREVIEW_SPLIT_STACKED, true)

    /**
     * The reference scan's default zoom fit. Width by default: the scan pane
     * is usually shorter than it is wide now that [previewSplitStacked]
     * stacks it above the render, and fitting to the whole page there leaves
     * the scan small with unused space on each side. Fitting to width uses
     * the space actually available, at the cost of scrolling down the page —
     * which is how a reader treats a real book anyway.
     *
     * Returns an `ImageAnnotationCanvas.FitMode` id; an unrecognised value
     * falls back to width rather than failing to open an editor.
     */
    fun previewImageFitMode(): ImageAnnotationCanvas.FitMode =
        when (string(PREVIEW_IMAGE_FIT_MODE, PREVIEW_IMAGE_FIT_WIDTH).lowercase()) {
            "page" -> ImageAnnotationCanvas.FitMode.PAGE
            else -> ImageAnnotationCanvas.FitMode.WIDTH
        }

    // ---- Registry plumbing ----------------------------------------------

    const val TOGGLE_ENABLED: String = "wikitext.editing.toggle.enabled"
    const val TOGGLE_PROMOTE: String = "wikitext.editing.toggle.promote"
    const val PREVIEW_MODE: String = "wikitext.editing.preview.mode"
    const val PREVIEW_SPLIT_STACKED: String = "wikitext.editing.preview.splitStacked"
    const val PREVIEW_IMAGE_FIT_MODE: String = "wikitext.editing.preview.imageFitMode"
    private const val PREVIEW_IMAGE_FIT_WIDTH = "width"
    private const val PREVIEW_MODE_BOTH = "both"
    const val SURROUND_ENABLED: String = "wikitext.editing.surround.enabled"
    const val SURROUND_STRATEGY: String = "wikitext.editing.surround.strategy"
    const val VARIABLE_PROMPT: String = "wikitext.editing.variablePrompt"

    /**
     * Registry lookups throw when a key is missing, which happens in unit
     * tests that never load the plugin descriptor. A prototype switch is not
     * worth failing a test over, so an absent key falls back to the default.
     */
    private fun boolean(key: String, default: Boolean): Boolean =
        runCatching { Registry.`is`(key, default) }
            .onFailure { thisLogger().debug("registry key $key unavailable, using $default", it) }
            .getOrDefault(default)

    private fun string(key: String, default: String): String =
        runCatching { Registry.stringValue(key) }
            .onFailure { thisLogger().debug("registry key $key unavailable, using $default", it) }
            .getOrDefault(default)
            .ifBlank { default }
}
