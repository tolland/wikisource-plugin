package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.Disposable
import com.intellij.openapi.application.runReadActionBlocking
import com.intellij.openapi.editor.event.DocumentEvent
import com.intellij.openapi.editor.event.DocumentListener
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.fileEditor.FileEditor
import com.intellij.openapi.fileEditor.FileEditorState
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.util.UserDataHolderBase
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.ui.JBSplitter
import com.intellij.ui.components.JBPanel
import java.awt.BorderLayout
import java.awt.Component
import java.awt.KeyboardFocusManager
import java.beans.PropertyChangeListener
import javax.swing.JComponent
import javax.swing.SwingUtilities

/**
 * this is provided to the right pane of TextEditorWithPreview
 * it is an implementation of FileEditor
 *
 * It hosts the two proofread previews — the reference scan
 * ([ReferenceImagePane]) and the server-rendered wikitext ([RenderPreviewPane])
 * — and lets the user show either one alone or both tiled together for
 * side-by-side comparison. A master toolbar ([PrpPreviewToolbar]) at the top
 * picks the [mode] and, in the tiled [Mode.SPLIT] mode, the [splitStacked]
 * orientation; each preview carries its own toolbar with the controls specific
 * to it (zoom/OCR for the scan, reload for the render).
 */
class PrpPreviewBrowser(
    private val file: VirtualFile,
) : UserDataHolderBase(), FileEditor, Disposable {

    /** Which preview(s) the right side shows. */
    enum class Mode { IMAGE_ONLY, RENDER_ONLY, SPLIT }

    /** The two previews, for [activePreviewKind] / structure-view purposes. */
    enum class PaneKind { IMAGE, RENDER }

    private val component = JBPanel<JBPanel<*>>(BorderLayout())

    private val renderPane = RenderPreviewPane(file).also {
        Disposer.register(this, it)
    }

    private val imagePane =
        ReferenceImagePane(file).also { Disposer.register(this, it) }

    /** The scan pane, for profiles that have one — box↔text linking wires into it. */
    val referenceImagePane: ReferenceImagePane
        get() = imagePane

    // Each preview is wrapped with its own toolbar so the pane-specific
    // controls travel with it into the tiled layout.
    private val imageHost = paneHost(
        PrpImagePreviewToolbar(imagePane).component,
        imagePane.component,
    )
    private val renderHost = paneHost(
        PrpRenderPreviewToolbar(::reloadPreview, renderPane.component).component,
        renderPane.component,
    )

    // Reused across mode changes; its orientation follows [splitStacked].
    private val splitter = JBSplitter(false, 0.5f).apply {
        setHonorComponentsMinimumSize(false)
    }

    private val centerPanel = JBPanel<JBPanel<*>>(BorderLayout())

    /**
     * Notified when the visible/active preview changes — a mode switch, or (in
     * the tiled mode) focus crossing between the two previews. The host
     * ([PrpFileEditor]) uses this to refresh the structure view, whose content
     * depends on which preview is active.
     */
    var onPaneChanged: (() -> Unit)? = null

    @Volatile
    private var disposed = false

    /**
     * Which preview(s) are shown. The reference scan is the initial view
     * (wikisource editor convention). Changing it re-lays out the center and
     * notifies [onPaneChanged].
     */
    var mode: Mode = Mode.IMAGE_ONLY
        set(value) {
            if (field != value) {
                field = value
                applyLayout()
            }
        }

    /**
     * Tiling orientation for [Mode.SPLIT]: `true` stacks the previews top and
     * bottom, `false` places them side by side. Ignored outside SPLIT.
     */
    var splitStacked: Boolean = false
        set(value) {
            if (field != value) {
                field = value
                if (mode == Mode.SPLIT) {
                    applyLayout()
                }
            }
        }

    // In SPLIT both previews are visible, so which one is "active" (for the
    // structure view) is decided by focus. Updated by [focusListener].
    private var focusedKind: PaneKind = PaneKind.IMAGE

    private val focusListener = PropertyChangeListener { event ->
        val owner = event.newValue as? Component ?: return@PropertyChangeListener
        val kind = when {
            SwingUtilities.isDescendingFrom(owner, imageHost) -> PaneKind.IMAGE
            SwingUtilities.isDescendingFrom(owner, renderHost) -> PaneKind.RENDER
            else -> return@PropertyChangeListener
        }
        if (kind != focusedKind) {
            focusedKind = kind
            if (mode == Mode.SPLIT) {
                onPaneChanged?.invoke()
            }
        }
    }

    init {
        component.add(PrpPreviewToolbar(this).component, BorderLayout.NORTH)
        component.add(centerPanel, BorderLayout.CENTER)

        // Arm the render pane's first load before laying out: scheduleReload()
        // only marks it pending while the pane is hidden, so the render is
        // populated the moment it first becomes visible (a mode switch to
        // SPLIT/RENDER_ONLY) rather than staying blank until the first edit.
        renderPane.scheduleReload()

        // Apply the initial mode (IMAGE_ONLY): the property initializer sets the
        // backing field directly without firing the setter, so lay out here.
        applyLayout()

        KeyboardFocusManager.getCurrentKeyboardFocusManager()
            .addPropertyChangeListener("focusOwner", focusListener)

        runReadActionBlocking {
            FileDocumentManager.getInstance().getDocument(file)?.addDocumentListener(object : DocumentListener {
                override fun documentChanged(event: DocumentEvent) {
                    renderPane.scheduleReload()
                }
            }, this)
        }
    }

    /**
     * Rebuilds the center to match [mode]/[splitStacked] and reconciles each
     * pane's loaded/visible state:
     * - the scan is loaded lazily the first time it becomes visible;
     * - the render pane tracks visibility so edits arriving while it is hidden
     *   are coalesced into one reload when it is next shown.
     */
    private fun applyLayout() {
        centerPanel.removeAll()
        when (mode) {
            Mode.IMAGE_ONLY -> centerPanel.add(imageHost, BorderLayout.CENTER)
            Mode.RENDER_ONLY -> centerPanel.add(renderHost, BorderLayout.CENTER)
            Mode.SPLIT -> {
                splitter.orientation = splitStacked
                splitter.firstComponent = imageHost
                splitter.secondComponent = renderHost
                centerPanel.add(splitter, BorderLayout.CENTER)
            }
        }

        val imageShown = mode != Mode.RENDER_ONLY
        val renderShown = mode != Mode.IMAGE_ONLY
        if (imageShown) {
            imagePane.ensureLoaded()
        }
        // scheduleReload() marked the render pending while hidden; the setter
        // flushes that pending reload when the pane becomes visible.
        renderPane.visible = renderShown

        centerPanel.revalidate()
        centerPanel.repaint()
        onPaneChanged?.invoke()
    }

    /**
     * The preview the structure view should reflect: the sole visible pane, or
     * — when both are tiled — whichever last held focus.
     */
    fun activePreviewKind(): PaneKind = when (mode) {
        Mode.IMAGE_ONLY -> PaneKind.IMAGE
        Mode.RENDER_ONLY -> PaneKind.RENDER
        Mode.SPLIT -> focusedKind
    }

    /**
     * Ensures the reference scan is visible and treated as active — used when
     * navigating to a bounding box from the structure view or a gutter icon.
     * If only the render is showing, switches to the scan; a tiled layout is
     * left as-is (the scan is already visible).
     */
    fun revealImagePane() {
        if (mode == Mode.RENDER_ONLY) {
            mode = Mode.IMAGE_ONLY
        }
        imagePane.ensureLoaded()
        if (focusedKind != PaneKind.IMAGE) {
            focusedKind = PaneKind.IMAGE
            onPaneChanged?.invoke()
        }
    }

    private fun paneHost(toolbar: JComponent, content: JComponent): JComponent =
        JBPanel<JBPanel<*>>(BorderLayout()).apply {
            add(toolbar, BorderLayout.NORTH)
            add(content, BorderLayout.CENTER)
        }

    fun reloadPreview() {
        if (!disposed) {
            renderPane.reload()
        }
    }

    override fun getComponent(): JComponent = component

    override fun getPreferredFocusedComponent(): JComponent =
        if (activePreviewKind() == PaneKind.IMAGE) imagePane.component else renderPane.component

    override fun getName(): String = "Wikitext Preview"

    override fun setState(state: FileEditorState) = Unit

    override fun isModified(): Boolean = false

    override fun isValid(): Boolean = !disposed && file.isValid

    override fun addPropertyChangeListener(listener: PropertyChangeListener) = Unit

    override fun removePropertyChangeListener(listener: PropertyChangeListener) = Unit

    override fun getFile(): VirtualFile = file

    override fun dispose() {
        disposed = true
        KeyboardFocusManager.getCurrentKeyboardFocusManager()
            .removePropertyChangeListener("focusOwner", focusListener)
    }
}
