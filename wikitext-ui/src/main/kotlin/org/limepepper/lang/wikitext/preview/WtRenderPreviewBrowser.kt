package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditor
import com.intellij.openapi.fileEditor.FileEditorState
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.util.IconLoader
import com.intellij.openapi.util.UserDataHolderBase
import com.intellij.openapi.vfs.VfsUtilCore
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBPanel
import com.intellij.ui.jcef.JBCefApp
import com.intellij.ui.jcef.JBCefBrowser
import java.awt.BorderLayout
import java.beans.PropertyChangeListener
import javax.swing.Icon
import javax.swing.JComponent
import javax.swing.Timer

class WtRenderPreviewBrowser(

    private val project: Project,
    private val file: VirtualFile,
    private val textEditor: TextEditor,
) : UserDataHolderBase(), FileEditor, Disposable {
    private val log = logger<WtRenderPreviewBrowser>()
    private val component = JBPanel<JBPanel<*>>(BorderLayout())
    private val previewContainer = JBPanel<JBPanel<*>>(BorderLayout())
    private val reloadTimer = Timer(350) { reloadPreview() }.apply {
        isRepeats = false
    }

    private var scalarBrowser: JBCefBrowser? = null
    private var officialPreview: FileEditor? = null
    private var selectedRenderer = firstAvailableRenderer()
    private var disposed = false

    init {
        component.add(previewContainer, BorderLayout.CENTER)

        if (JBCefApp.isSupported()) {
            showSelectedRenderer()
        } else {
            showUnsupportedJcefMessage()
        }

        FileDocumentManager.getInstance().getDocument(file)?.addDocumentListener(object : DocumentListener {
            override fun documentChanged(event: DocumentEvent) {
                scheduleReload()
            }
        }, this)
    }

    private fun scheduleReload() {
        if (!disposed) {
            reloadTimer.restart()
        }
    }

    fun reloadPreview() {
        if (disposed) {
            return
        }

        ensureSelectedRendererIsAvailable()

        when (selectedRenderer) {
            PreviewRenderer.SCALAR -> loadScalarPreview()
            PreviewRenderer.REDOC, PreviewRenderer.SWAGGER_UI -> reloadOfficialPreview()
        }
    }

    fun nextRenderer(): PreviewRenderer {
        val renderers = availableRenderers()
        val currentIndex = renderers.indexOf(selectedRenderer).takeIf { it >= 0 } ?: 0

        return renderers[(currentIndex + 1) % renderers.size]
    }

    fun canSwitchRenderer(): Boolean = availableRenderers().size > 1

    fun switchToNextRenderer() {
        selectedRenderer = nextRenderer()
        showSelectedRenderer()
    }

    private fun showSelectedRenderer() {
        if (disposed) {
            return
        }

        if (!JBCefApp.isSupported()) {
            showUnsupportedJcefMessage()
            return
        }

        ensureSelectedRendererIsAvailable()

        previewContainer.removeAll()

        when (selectedRenderer) {
            PreviewRenderer.SCALAR -> showScalarPreview()
            PreviewRenderer.REDOC, PreviewRenderer.SWAGGER_UI -> showOfficialPreview(selectedRenderer)
        }

        previewContainer.revalidate()
        previewContainer.repaint()
    }

    private fun showScalarPreview() {
        disposeOfficialPreview()
        disposeScalarBrowser()

        val currentBrowser = JBCefBrowser().also {
            scalarBrowser = it
            previewContainer.add(it.component, BorderLayout.CENTER)
        }

        loadScalarPreview(currentBrowser)
    }

    private fun showOfficialPreview(renderer: PreviewRenderer) {
        disposeScalarBrowser()
        disposeOfficialPreview()

        val swaggerSupport = SwaggerPreviewSupport.getInstance()
        if (swaggerSupport == null) {
            selectedRenderer = firstAvailableRenderer()
            showScalarPreview()
            return
        }

        runCatching {
            when (renderer) {
                PreviewRenderer.REDOC -> swaggerSupport.createRedoc(file, textEditor, project)
                PreviewRenderer.SWAGGER_UI -> swaggerSupport.createSwaggerUi(file, textEditor, project)
                PreviewRenderer.SCALAR -> null
            }
        }.onSuccess { preview ->
            if (preview == null) {
                previewContainer.add(JBLabel("${renderer.presentableName} is not available."), BorderLayout.CENTER)
            } else {
                officialPreview = preview
                previewContainer.add(preview.component, BorderLayout.CENTER)
            }
        }.onFailure { error ->
            log.warn("Failed to create ${renderer.presentableName} preview for ${file.path}", error)
            previewContainer.add(
                JBLabel("${renderer.presentableName} preview failed to load: ${error.message ?: "Unknown error"}"),
                BorderLayout.CENTER,
            )
        }
    }

    private fun reloadOfficialPreview() {
        val currentPreview = officialPreview
        if (currentPreview == null) {
            showSelectedRenderer()
            return
        }
        val swaggerSupport = SwaggerPreviewSupport.getInstance()
        if (swaggerSupport == null) {
            showSelectedRenderer()
            return
        }

        val reloaded = runCatching {
            swaggerSupport.reload(currentPreview, file)
        }.onFailure { error ->
            log.warn("Failed to reload ${selectedRenderer.presentableName} preview for ${file.path}", error)
        }.getOrDefault(false)

        if (!reloaded) {
            showSelectedRenderer()
        }
    }

    private fun loadScalarPreview(currentBrowser: JBCefBrowser? = scalarBrowser) {
        val browser = currentBrowser ?: return
        if (disposed) {
            return
        }

        val html = runCatching {
            val specification = readSpecification()
            renderScalarPreviewHtml(file.name, specification, file.extension, isDarkEditorTheme())
        }.getOrElse { error ->
            log.warn("Failed to render OpenAPI preview for ${file.path}", error)
            renderErrorHtml(
                "Unable to load ${file.name}",
                error.message ?: "Unknown error",
                isDarkEditorTheme(),
            )
        }

        ApplicationManager.getApplication().invokeLater {
            if (!disposed) {
                browser.loadHTML(html, "https://scalar-openapi-preview.local/${file.name}")
            }
        }
    }

    private fun readSpecification(): String {
        val document = FileDocumentManager.getInstance().getDocument(file)
        return document?.text ?: VfsUtilCore.loadText(file)
    }

    override fun getComponent(): JComponent = component

    override fun getPreferredFocusedComponent(): JComponent =
        officialPreview?.preferredFocusedComponent ?: scalarBrowser?.component ?: component

    override fun getName(): String = "OpenAPI Preview"

    override fun setState(state: FileEditorState) = Unit

    override fun isModified(): Boolean = false

    override fun isValid(): Boolean = !disposed && file.isValid

    override fun addPropertyChangeListener(listener: PropertyChangeListener) = Unit

    override fun removePropertyChangeListener(listener: PropertyChangeListener) = Unit

    override fun getFile(): VirtualFile = file

    override fun dispose() {
        disposed = true
        reloadTimer.stop()
        disposeScalarBrowser()
        disposeOfficialPreview()
    }

    private fun showUnsupportedJcefMessage() {
        previewContainer.removeAll()
        previewContainer.add(
            JBLabel("OpenAPI preview requires JCEF, but JCEF is not available in this IDE runtime."),
            BorderLayout.CENTER,
        )
        previewContainer.revalidate()
        previewContainer.repaint()
    }

    private fun disposeScalarBrowser() {
        scalarBrowser?.let {
            Disposer.dispose(it)
        }
        scalarBrowser = null
    }

    private fun disposeOfficialPreview() {
        officialPreview?.let { preview ->
            runCatching {
                preview.dispose()
            }.onFailure { error ->
                log.warn("Failed to dispose ${selectedRenderer.presentableName} preview for ${file.path}", error)
            }
        }
        officialPreview = null
    }

    private fun ensureSelectedRendererIsAvailable() {
        if (selectedRenderer !in availableRenderers()) {
            selectedRenderer = firstAvailableRenderer()
        }
    }

    private fun firstAvailableRenderer(): PreviewRenderer {
        return availableRenderers().firstOrNull() ?: PreviewRenderer.SCALAR
    }

    private fun availableRenderers(): List<PreviewRenderer> {
        val availableRenderers = if (SwaggerPreviewSupport.isAvailable()) {
            PreviewRenderer.entries.toSet()
        } else {
            setOf(PreviewRenderer.SCALAR)
        }

        return OpenApiPreviewSettings.instance.rendererOrder().filter { it in availableRenderers }
    }
}

internal enum class PreviewRenderer(
    val presentableName: String,
    val icon: Icon,
) {
    SCALAR("Scalar", PreviewIcons.scalar),
    REDOC("Redoc", PreviewIcons.redoc),
    SWAGGER_UI("Swagger UI", PreviewIcons.swaggerUi);

    override fun toString(): String = presentableName
}

private object PreviewIcons {
    val scalar: Icon = IconLoader.getIcon("/icons/scalar.svg", PreviewIcons::class.java)
    val redoc: Icon = IconLoader.getIcon("/icons/redoc.svg", PreviewIcons::class.java)
    val swaggerUi: Icon = IconLoader.getIcon("/icons/swagger-ui.svg", PreviewIcons::class.java)
}