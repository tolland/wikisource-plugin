package org.limepepper.lang.wikitext.settings

import com.intellij.codeInsight.daemon.DaemonCodeAnalyzer
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.openapi.project.ProjectManager
import org.limepepper.lang.wikitext.highlighting.QuietSentenceBandHighlighting
import org.limepepper.lang.wikitext.highlighting.SentenceBandHighlightingStrategy

/** Application-wide presentation settings; boundary detection does not depend on them. */
@Service(Service.Level.APP)
@State(name = "WtHighlightingSettings", storages = [Storage("wikitext-highlighting.xml")])
class WtHighlightingSettings : PersistentStateComponent<WtHighlightingSettings.Options> {
    data class Options(
        var bandsEnabled: Boolean = true,
        var bandStrength: Int = 35,
        var referencesEnabled: Boolean = true,
    )

    @Volatile
    private var options = Options()

    override fun getState(): Options = options.copy()

    override fun loadState(state: Options) {
        options = state.copy(bandStrength = state.bandStrength.coerceIn(0, 100))
    }

    fun update(value: Options) {
        val normalized = value.copy(bandStrength = value.bandStrength.coerceIn(0, 100))
        if (options == normalized) return
        options = normalized
        // Restart removes old annotations too, so disabling works without editing the file.
        ApplicationManager.getApplication().invokeLater {
            ProjectManager.getInstance().openProjects.filterNot { it.isDisposed }.forEach {
                DaemonCodeAnalyzer.getInstance(it).restart()
            }
        }
    }

    /** Snapshot once per file annotation pass, including the disabled case. */
    fun bandHighlighting(): SentenceBandHighlightingStrategy? {
        val current = options
        if (!current.bandsEnabled || current.bandStrength == 0) return null
        return QuietSentenceBandHighlighting(current.bandStrength / 100.0)
    }

    companion object {
        fun getInstance(): WtHighlightingSettings =
            ApplicationManager.getApplication().getService(WtHighlightingSettings::class.java)
    }
}
