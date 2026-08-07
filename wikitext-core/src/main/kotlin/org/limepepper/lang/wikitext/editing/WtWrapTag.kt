package org.limepepper.lang.wikitext.editing

/**
 * Placeholder for the value a [WtWrapTag] needs filled in — see
 * [WtWrapTag.variablePrompt]. Chosen to look like a live-template variable
 * because one of the surround implementations turns it into exactly that.
 *
 * A top-level constant rather than a member of [WtWrapTag.Companion]: enum
 * entries are constructed before their companion object is initialized, so
 * [WtWrapTag.SECTION] cannot read it from there. [WtWrapTag.VARIABLE] aliases
 * it for callers, who should keep using that name.
 */
private const val VARIABLE_PLACEHOLDER: String = "\$NAME$"

/**
 * The catalog of constructs a selection can be wrapped in — the single source
 * of truth shared by Surround With, the formatting toggle actions, and (later)
 * intentions/completion, so a construct is described once rather than once per
 * feature.
 *
 * Deliberately a flat data table rather than anything PSI-aware: wrapping is a
 * *text* operation (see [WtWrapRenderer]), and wikitext PSI is far too loose to
 * build these trees by hand. The block/inline distinction here is only about
 * how the markers are laid out in the document; the separate, richer question
 * of how a tag *renders* lives in
 * [org.limepepper.lang.wikitext.tags.WtTagDisplayClassifier] and is not
 * duplicated here.
 *
 * ## Prototyping note
 *
 * Which entries are actually offered is not decided here — see
 * `WtWrapTagSets` for the curated subsets, and `WtEditingFlags` for the
 * runtime switches. Adding a construct should mean adding one entry to this
 * enum and nothing else.
 */
enum class WtWrapTag(
    /** Stable id, used in registry keys, action ids and test data. */
    val id: String,
    /** Human-readable name for the Surround With popup and action text. */
    val title: String,
    /** Text inserted before the selection. May contain [VARIABLE]. */
    val prefix: String,
    /** Text inserted after the selection. May contain [VARIABLE]. */
    val suffix: String,
    /**
     * True when the markers belong on their own lines. [WtWrapRenderer] adds
     * the line breaks, so the strings above stay free of layout noise.
     */
    val block: Boolean = false,
    /**
     * Prompt for the value that fills [VARIABLE] in [prefix]/[suffix], or null
     * when the construct takes no value. The only current user is [SECTION],
     * whose begin/end markers must carry the *same* name — which is why the
     * placeholder appears twice and the surrounders mirror it rather than
     * asking twice.
     */
    val variablePrompt: String? = null,
) {
    // ---- HTML-ish inline formatting -------------------------------------

    BOLD("bold", "Bold ('''…''')", "'''", "'''"),
    ITALIC("italic", "Italic (''…'')", "''", "''"),
    CODE("code", "<code>", "<code>", "</code>"),
    MATH("math", "<math>", "<math>", "</math>"),
    SMALL("small", "<small>", "<small>", "</small>"),
    SUP("sup", "<sup>", "<sup>", "</sup>"),
    SUB("sub", "<sub>", "<sub>", "</sub>"),

    // ---- Parser-control tags --------------------------------------------

    NOWIKI("nowiki", "<nowiki>", "<nowiki>", "</nowiki>"),
    PRE("pre", "<pre>", "<pre>", "</pre>", block = true),
    NOINCLUDE("noinclude", "<noinclude>", "<noinclude>", "</noinclude>", block = true),
    INCLUDEONLY("includeonly", "<includeonly>", "<includeonly>", "</includeonly>", block = true),
    ONLYINCLUDE("onlyinclude", "<onlyinclude>", "<onlyinclude>", "</onlyinclude>", block = true),

    // ---- Wikisource content ---------------------------------------------

    REF("ref", "<ref>", "<ref>", "</ref>"),
    POEM("poem", "<poem>", "<poem>", "</poem>", block = true),
    BLOCKQUOTE("blockquote", "<blockquote>", "<blockquote>", "</blockquote>", block = true),

    /**
     * Labeled Section Transclusion boundaries. Both markers name the same
     * section, so this is the one catalog entry that needs a value filled in —
     * and the reason the surround seam has to support variables at all.
     */
    SECTION(
        id = "section",
        title = "<section begin/end>",
        prefix = "<section begin=\"$VARIABLE_PLACEHOLDER\" />",
        suffix = "<section end=\"$VARIABLE_PLACEHOLDER\" />",
        block = true,
        variablePrompt = "Section name",
    ),
    ;

    /** True when this construct needs a value before it can be inserted. */
    val hasVariable: Boolean get() = variablePrompt != null

    companion object {
        /** Placeholder for the value described by [variablePrompt]. */
        const val VARIABLE: String = VARIABLE_PLACEHOLDER

        fun byId(id: String): WtWrapTag? = entries.firstOrNull { it.id == id }
    }
}

/**
 * Curated subsets of [WtWrapTag]. Which constructs belong in which UI surface
 * is a taste question that will change during prototyping, so it is isolated
 * here instead of being baked into the catalog or the actions.
 */
object WtWrapTagSets {
    /** Offered in the Surround With popup, in the order shown. */
    val surroundWith: List<WtWrapTag> = listOf(
        WtWrapTag.BOLD,
        WtWrapTag.ITALIC,
        WtWrapTag.CODE,
        WtWrapTag.MATH,
        WtWrapTag.NOWIKI,
        WtWrapTag.REF,
        WtWrapTag.SMALL,
        WtWrapTag.SUP,
        WtWrapTag.SUB,
        WtWrapTag.PRE,
        WtWrapTag.POEM,
        WtWrapTag.BLOCKQUOTE,
        WtWrapTag.NOINCLUDE,
        WtWrapTag.INCLUDEONLY,
        WtWrapTag.ONLYINCLUDE,
        WtWrapTag.SECTION,
    )

    /**
     * Constructs that get their own toggle action + keyboard shortcut (step 2
     * of the editing plan). Listed here so the catalog stays the only place
     * their markup is written down.
     */
    val toggleable: List<WtWrapTag> = listOf(
        WtWrapTag.BOLD,
        WtWrapTag.ITALIC,
        WtWrapTag.CODE,
        WtWrapTag.NOWIKI,
    )
}
