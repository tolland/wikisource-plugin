package org.limepepper.lang.wikitext.editor.prp

import org.limepepper.lang.wikitext.vfs.backend.OcrBackendInfo
import org.limepepper.lang.wikitext.vfs.settings.OcrFavorite

/**
 * One resolved entry of the "Run OCR" menu: a favourite that has been
 * matched to a backend the site actually offers.
 *
 * Resolution happens when the menu is built rather than when it is
 * clicked, so a favourite pinned to a backend that is gone (renamed,
 * disabled) simply doesn't appear, instead of producing an item that
 * fails on click.
 */
data class OcrMenuChoice(
    val backend: OcrBackendInfo,
    val favorite: OcrFavorite?,
    val label: String,
) {
    /** The engine to run: the favourite's, or the backend's configured default. */
    val engine: String? get() = favorite?.engine?.takeIf { it.isNotBlank() } ?: backend.defaultEngine

    companion object {
        /**
         * [favorites], in menu order, keeping only those runnable against
         * [available]. Duplicate labels are left alone: two favourites that
         * read the same are a settings problem the user can see and fix,
         * and silently renaming them would only hide it.
         */
        fun resolve(
            favorites: List<OcrFavorite>,
            available: List<OcrBackendInfo>,
        ): List<OcrMenuChoice> = favorites.mapNotNull { favorite ->
            favorite.resolveBackend(available)?.let { backend ->
                OcrMenuChoice(backend, favorite, favorite.displayName())
            }
        }

        /**
         * The fallback menu: every configured backend on its own defaults.
         * Shown when no favourite resolves — a site whose backends are all
         * configured but whose favourites all name something else must not
         * leave the user with an empty menu and no way forward.
         */
        fun defaults(available: List<OcrBackendInfo>): List<OcrMenuChoice> =
            available.map { backend ->
                OcrMenuChoice(
                    backend = backend,
                    favorite = null,
                    label = backend.defaultEngine
                        ?.let { "${backend.name} · $it" }
                        ?: backend.name,
                )
            }
    }
}
