package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage

@State(
    name = "ScalarOpenApiPreviewSettings",
    storages = [Storage("scalarOpenapiPreview.xml")],
)
internal class OpenApiPreviewSettings : PersistentStateComponent<OpenApiPreviewSettings.SettingsState> {
    private var state = SettingsState()

    override fun getState(): SettingsState = state

    override fun loadState(state: SettingsState) {
        this.state = state
    }

    fun rendererOrder(): List<PreviewRenderer> = normalizeRendererOrder(state.rendererOrder)

    fun setRendererOrder(renderers: List<PreviewRenderer>) {
        state.rendererOrder = normalizeRendererOrder(renderers.map { it.name })
            .map { it.name }
            .toMutableList()
    }

    fun hiddenScalarClients(): Set<String> = state.hiddenScalarClients.toSet()

    fun setHiddenScalarClients(hiddenClients: Set<String>) {
        state.hiddenScalarClients = hiddenClients.toMutableList()
    }

    internal class SettingsState {
        var rendererOrder: MutableList<String> = DEFAULT_RENDERER_ORDER.map { it.name }.toMutableList()
        var hiddenScalarClients: MutableList<String> = mutableListOf()
    }

    companion object {
        val instance: OpenApiPreviewSettings
            get() = ApplicationManager.getApplication().getService(OpenApiPreviewSettings::class.java)

        val DEFAULT_RENDERER_ORDER: List<PreviewRenderer> = listOf(
            PreviewRenderer.SCALAR,
            PreviewRenderer.REDOC,
            PreviewRenderer.SWAGGER_UI,
        )

        fun normalizeRendererOrder(rendererNames: List<String>): List<PreviewRenderer> {
            val configuredRenderers = rendererNames.mapNotNull { rendererName ->
                runCatching { PreviewRenderer.valueOf(rendererName) }.getOrNull()
            }
            val orderedRenderers = (configuredRenderers + DEFAULT_RENDERER_ORDER).distinct()

            return orderedRenderers.filter { it in DEFAULT_RENDERER_ORDER }
        }
    }
}
