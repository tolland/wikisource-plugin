package org.limepepper.lang.wikitext.vfs.settings

import org.limepepper.lang.wikitext.vfs.backend.OcrBackendInfo
import org.limepepper.lang.wikitext.vfs.backend.OcrRunRequest

/**
 * One entry in the "Run OCR" menu: an engine, and the languages to run it
 * with. A page's OCR backend offers far more than anyone wants in a
 * context menu — `GET /api/models` on a stock Wikimedia OCR instance
 * returns hundreds of languages for Google Vision alone — but the useful
 * set for any given work is tiny and stable: two or three text models for
 * the language it's printed in, and an ATR model or two for its formulae.
 * A favourite is that choice, made once and reused.
 *
 * Everything but [engine] is optional so a favourite can lean on the
 * backend's own configured defaults: a null [backend] means "whichever
 * backend the site lists first", and empty [langs] means "whatever the
 * backend config says", which is the right answer for an engine with no
 * language dimension at all (pix2tex reads mathematical notation).
 *
 * A mutable class with a no-arg constructor rather than a data class: this
 * is serialized straight into the IDE's XML by
 * [com.intellij.util.xmlb.XmlSerializer], which needs to construct and
 * populate instances reflectively.
 */
class OcrFavorite() {
    var backend: String? = null
    var engine: String = ""
    var langs: MutableList<String> = mutableListOf()

    /** Overrides the generated menu text when set. */
    var label: String? = null

    /** Sent to prompt-capable backends; ignored (harmlessly) by the rest. */
    var prompt: String? = null

    constructor(
        engine: String,
        langs: List<String> = emptyList(),
        backend: String? = null,
        label: String? = null,
        prompt: String? = null,
    ) : this() {
        this.engine = engine
        this.langs = langs.toMutableList()
        this.backend = backend
        this.label = label
        this.prompt = prompt
    }

    /**
     * The menu text: [label] when the user set one, otherwise the engine
     * plus its languages ("tesseract · en, de"). The backend name is only
     * appended when the favourite pins one, since with a single configured
     * backend — the common case — repeating its name in every item is
     * noise.
     */
    fun displayName(): String {
        label?.takeIf { it.isNotBlank() }?.let { return it }
        val base = if (langs.isEmpty()) engine else "$engine · ${langs.joinToString(", ")}"
        return backend?.takeIf { it.isNotBlank() }?.let { "$base [$it]" } ?: base
    }

    /** True when this favourite can run against [available]. */
    fun isRunnableWith(available: List<OcrBackendInfo>): Boolean {
        if (engine.isBlank()) return false
        val name = backend?.takeIf { it.isNotBlank() } ?: return available.isNotEmpty()
        return available.any { it.name == name }
    }

    /**
     * The backend this favourite runs against, or null when it pins one
     * that the site does not (any more) offer.
     */
    fun resolveBackend(available: List<OcrBackendInfo>): OcrBackendInfo? {
        val name = backend?.takeIf { it.isNotBlank() } ?: return available.firstOrNull()
        return available.find { it.name == name }
    }

    /**
     * A run request for [box], leaving unset fields for the sidecar to fill
     * from the backend's configured defaults — empty [langs] must travel as
     * null, not as an empty list, or it would override those defaults with
     * "no languages".
     */
    fun toRunRequest(
        backendName: String,
        annotationId: String? = null,
        boxX: Double? = null,
        boxY: Double? = null,
        boxWidth: Double? = null,
        boxHeight: Double? = null,
        imageBase64: String? = null,
    ): OcrRunRequest = OcrRunRequest(
        backend = backendName,
        annotationId = annotationId,
        boxX = boxX,
        boxY = boxY,
        boxWidth = boxWidth,
        boxHeight = boxHeight,
        imageBase64 = imageBase64,
        engine = engine.takeIf { it.isNotBlank() },
        langs = langs.takeIf { it.isNotEmpty() }?.toList(),
        prompt = prompt?.takeIf { it.isNotBlank() },
    )

    fun copy(): OcrFavorite = OcrFavorite(engine, langs.toList(), backend, label, prompt)

    override fun equals(other: Any?): Boolean = other is OcrFavorite &&
        other.backend == backend &&
        other.engine == engine &&
        other.langs == langs &&
        other.label == label &&
        other.prompt == prompt

    override fun hashCode(): Int =
        listOf(backend, engine, langs, label, prompt).hashCode()

    override fun toString(): String = displayName()
}
