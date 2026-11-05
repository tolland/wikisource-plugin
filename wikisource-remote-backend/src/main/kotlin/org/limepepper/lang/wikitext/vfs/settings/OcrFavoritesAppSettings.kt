package org.limepepper.lang.wikitext.vfs.settings

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.Service.Level
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.util.xmlb.annotations.XCollection

/**
 * The application-wide default "Run OCR" menu, used by every project that
 * has not set its own (see [OcrFavoritesProjectSettings]).
 *
 * Most people work on one wiki in one language and want the same handful of
 * engines everywhere; a per-project list only earns its keep for a work
 * that needs something unusual. So the app level holds the everyday
 * answer and the project level is an override, not a required setup step.
 */
@State(name = "WtOcrFavorites", storages = [Storage("wikitext-ocr.xml")])
@Service(Level.APP)
class OcrFavoritesAppSettings : PersistentStateComponent<OcrFavoritesAppSettings.State> {

    class State {
        @XCollection(style = XCollection.Style.v2)
        var favorites: MutableList<OcrFavorite> = defaultFavorites().toMutableList()
    }

    private var state = State()

    override fun getState(): State = state

    override fun loadState(state: State) {
        this.state = state
    }

    var favorites: List<OcrFavorite>
        get() = state.favorites.toList()
        set(value) {
            state.favorites = value.map { it.copy() }.toMutableList()
        }

    companion object {
        /**
         * The out-of-the-box menu. Tesseract in English is the free, local,
         * always-available baseline; pix2tex covers the other half of the
         * job (mathematical notation) and needs no language. Neither pins a
         * backend, so both work against whatever the site has configured.
         */
        fun defaultFavorites(): List<OcrFavorite> = listOf(
            OcrFavorite(engine = "tesseract", langs = listOf("en")),
            OcrFavorite(engine = "pix2tex", label = "pix2tex (LaTeX)"),
        )

        fun getInstance(): OcrFavoritesAppSettings =
            ApplicationManager.getApplication().getService(OcrFavoritesAppSettings::class.java)
    }
}
