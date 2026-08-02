package org.limepepper.lang.wikitext.vfs.settings

import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.Service.Level
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.openapi.project.Project
import com.intellij.util.xmlb.annotations.XCollection

/**
 * A project's own "Run OCR" menu, overriding the application defaults.
 *
 * The override is all-or-nothing and gated on [useProjectFavorites] rather
 * than on the list being non-empty: "this project deliberately offers
 * nothing but the raw backends" has to be expressible, and an empty list
 * cannot say that if empty also means "fall back".
 */
@State(name = "WtOcrFavorites", storages = [Storage("wikitext-ocr.xml")])
@Service(Level.PROJECT)
class OcrFavoritesProjectSettings :
    PersistentStateComponent<OcrFavoritesProjectSettings.State> {

    class State {
        var useProjectFavorites: Boolean = false

        @XCollection(style = XCollection.Style.v2)
        var favorites: MutableList<OcrFavorite> = mutableListOf()
    }

    private var state = State()

    override fun getState(): State = state

    override fun loadState(state: State) {
        this.state = state
    }

    var useProjectFavorites: Boolean
        get() = state.useProjectFavorites
        set(value) {
            state.useProjectFavorites = value
        }

    var favorites: List<OcrFavorite>
        get() = state.favorites.toList()
        set(value) {
            state.favorites = value.map { it.copy() }.toMutableList()
        }

    /**
     * What the menu should actually show: the project's list when it has
     * opted in, the application defaults otherwise.
     */
    fun effectiveFavorites(): List<OcrFavorite> =
        if (state.useProjectFavorites) favorites
        else OcrFavoritesAppSettings.getInstance().favorites

    companion object {
        fun getInstance(project: Project): OcrFavoritesProjectSettings =
            project.getService(OcrFavoritesProjectSettings::class.java)
    }
}
