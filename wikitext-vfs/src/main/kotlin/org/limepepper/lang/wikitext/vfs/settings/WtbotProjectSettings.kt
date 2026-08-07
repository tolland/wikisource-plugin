package org.limepepper.lang.wikitext.vfs.settings

import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.Service.Level
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.openapi.project.Project
import com.intellij.util.messages.Topic

/**
 * Project-level settings for the wtbot backend (host, port, timeout).
 * Notifies listeners on change via MessageBus Topic.
 */
@State(name = "WtbotProjectSettings", storages = [Storage("wikitext-vfs.xml")])
@Service(Level.PROJECT)
class WtbotProjectSettings(private val project: Project) : PersistentStateComponent<WtbotProjectSettings.State> {

    data class State(
        var host: String = "127.0.100.1",
        var port: Int = 18564,
        var timeoutSeconds: Int = 10
    )

    private var state = State()

    override fun getState(): State = state

    override fun loadState(state: State) {
        this.state = state
    }

    var host: String
        get() = state.host
        set(value) {
            if (state.host != value) {
                state.host = value
                project.messageBus.syncPublisher(TOPIC).settingsChanged(state.copy())
            }
        }

    var port: Int
        get() = state.port
        set(value) {
            if (state.port != value) {
                state.port = value
                project.messageBus.syncPublisher(TOPIC).settingsChanged(state.copy())
            }
        }

    var timeoutSeconds: Int
        get() = state.timeoutSeconds
        set(value) {
            if (state.timeoutSeconds != value) {
                state.timeoutSeconds = value
                project.messageBus.syncPublisher(TOPIC).settingsChanged(state.copy())
            }
        }

    val baseUrl: String
        get() = "http://${state.host}:${state.port}"

    companion object {
        val TOPIC: Topic<WtbotSettingsListener> =
            Topic.create("WtbotProjectSettings", WtbotSettingsListener::class.java)

        fun getInstance(project: Project): WtbotProjectSettings =
            project.getService(WtbotProjectSettings::class.java)
    }
}

/** Listener invoked when project settings change. */
fun interface WtbotSettingsListener {
    fun settingsChanged(state: WtbotProjectSettings.State)
}
