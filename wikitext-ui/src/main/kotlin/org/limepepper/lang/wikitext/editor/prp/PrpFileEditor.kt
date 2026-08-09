package org.limepepper.lang.wikitext.editor.prp

import com.intellij.ide.impl.StructureViewWrapperImpl
import com.intellij.ide.structureView.StructureViewBuilder
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.diagnostic.logger
import com.intellij.openapi.fileEditor.TextEditor
import com.intellij.openapi.fileEditor.TextEditorWithPreview
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.vfs.VirtualFile
import org.limepepper.lang.wikitext.annotation.BoundingBox
import org.limepepper.lang.wikitext.vfs.WtVirtualFile
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.awt.Component
import java.awt.KeyboardFocusManager
import java.beans.PropertyChangeListener
import javax.swing.SwingUtilities

private val PRP_LOG = logger<PrpFileEditor>()

/**
 * Provides an implementation of FileEditor, suitable for use by [PrpFileEditorProvider] via its' [com.intellij.openapi.fileEditor.FileEditorProvider.createEditor] method.
 */
class PrpFileEditor private constructor(
    private val project: Project,
    private val editorHalf: PrpTextEditor,
    private val previewHalf: PrpPreviewBrowser,
    private val file: VirtualFile,
) : TextEditorWithPreview(editorHalf, previewHalf) {
    constructor(project: Project, editor: TextEditor, file: VirtualFile) :
        this(
            project,
            PrpTextEditor(editor),
            PrpPreviewBrowser(file),
            file,
        )

    @Volatile
    private var disposed = false

    // Wired in init; fields so navigation can follow a box's link.
    private lateinit var rangeModel: TextRangeModel
    private lateinit var linkModel: BoxLinkModel
    private lateinit var anchorManager: WtTextRangeManager

    /** The site's OCR backends, loaded async in init; empty until then. */
    @Volatile
    private var ocrBackends: List<org.limepepper.lang.wikitext.vfs.backend.OcrBackendInfo> = emptyList()

    /** Which pane's structure the Structure tool window should reflect. */
    enum class ActivePane { EDITOR, PREVIEW_RENDER, PREVIEW_IMAGE }

    // In SHOW_EDITOR_AND_PREVIEW both panes are visible, so "active" is decided
    // by focus; the split layouts pin it. Updated by [focusListener].
    private var previewFocused = false

    // Fires whenever focus crosses between the two panes so the structure view,
    // which differs per pane, can be refreshed.
    private val focusListener = PropertyChangeListener { event ->
        val owner = event.newValue as? Component ?: return@PropertyChangeListener
        val inPreview = SwingUtilities.isDescendingFrom(owner, previewHalf.component)
        val inEditor = SwingUtilities.isDescendingFrom(owner, editorHalf.component)
        if ((inPreview || inEditor) && inPreview != previewFocused) {
            previewFocused = inPreview
            refreshStructureView()
        }
    }

    init {
        // Initialize TextEditorWithPreview's lazy UI before disposal-sensitive editor switching can occur.
        component

        // Independent transcription text ranges: rendered/edited in the body
        // editor by the manager, loaded once from the sidecar, persisted
        // write-behind. Offsets are body-relative (see WtTextRangeManager), so
        // the manager translates them against the guarded header's end offset.
        val pane = previewHalf.referenceImagePane
        val rangeModel = TextRangeModel()
        val linkModel = BoxLinkModel()
        val anchorManager = WtTextRangeManager(
            editorHalf.bodyEditor,
            rangeModel,
            bodyStartOffset = { editorHalf.bodyStartOffset },
            bodyEndOffset = { editorHalf.bodyEndOffset },
            revidSupplier = { pane.baseRevid },
            // A range wears its linked box's category color, if it has one —
            // several boxes may link to one range, so the first with a
            // category wins rather than picking arbitrarily between equals.
            categoryForRange = { rangeId ->
                linkModel.boxesFor(rangeId).firstNotNullOfOrNull { boxId -> pane.model[boxId]?.category }
            },
        )
        Disposer.register(this, anchorManager)
        this.linkModel = linkModel
        this.rangeModel = rangeModel
        this.anchorManager = anchorManager
        loadTextRanges(rangeModel, linkModel)

        // Box↔range linking. The box menu carries the simple path (a dropdown
        // of the page's ranges); the link handle on each box carries the
        // drag path — drag it across to a range's extent/handles or its
        // gutter icon and release.
        val revealRange: (String) -> Unit = { rangeId ->
            rangeModel.select(rangeId)
            anchorManager.reveal(rangeId)
        }
        pane.installPopupMenu(
            BoxCanvasPopup(
                pane.model,
                rangeModel,
                linkModel,
                rangeLabel = ::rangeMenuLabel,
                onRevealRange = revealRange,
                ocrBackends = { ocrBackends },
                onRunOcr = ::runOcr,
                ocrFavorites = {
                    org.limepepper.lang.wikitext.vfs.settings.OcrFavoritesProjectSettings
                        .getInstance(project)
                        .effectiveFavorites()
                },
                onConfigureOcr = ::configureOcrFavorites,
            )::menuFor,
        )
        loadOcrBackends()
        pane.installLinkDrag(
            linked = linkModel::isLinked,
            drop = { boxId, screenPoint ->
                anchorManager.rangeIdAtScreenPoint(screenPoint)?.let { rangeId ->
                    linkModel.link(boxId, rangeId)
                    revealRange(rangeId)
                }
            },
        )

        // A link is only meaningful while both endpoints exist: deleting a
        // range (or replacing the set) or deleting a box invalidates it. The
        // box side is gated on boxesLoaded so the pre-load empty model isn't
        // mistaken for "all boxes deleted".
        rangeModel.addListener(object : TextRangeModel.Listener {
            override fun rangesChanged() {
                linkModel.retainRanges(rangeModel.ranges().mapTo(HashSet()) { it.id })
            }
        })
        pane.model.addListener(object : org.limepepper.lang.wikitext.annotation.BoundingBoxModel.Listener {
            override fun boxesChanged() {
                if (pane.boxesLoaded) {
                    linkModel.retainBoxes(pane.model.boxes().mapTo(HashSet()) { it.id })
                }
                // A box's category may have changed (not just its geometry or
                // its existence), which can change a linked range's color.
                anchorManager.reconcile()
            }
        })
        linkModel.addListener(object : BoxLinkModel.Listener {
            override fun linksChanged() {
                pane.repaintCanvas()
                // A link changing which box a range points at can change the
                // category -- hence color -- that range now matches.
                anchorManager.reconcile()
            }
        })

        // Toggling the preview card (scan ↔ rendered HTML) changes which
        // structure applies, as does moving focus between the panes.
        previewHalf.onPaneChanged = ::refreshStructureView
        KeyboardFocusManager.getCurrentKeyboardFocusManager()
            .addPropertyChangeListener("focusOwner", focusListener)
        Disposer.register(this) {
            KeyboardFocusManager.getCurrentKeyboardFocusManager()
                .removePropertyChangeListener("focusOwner", focusListener)
        }
    }

    /**
     * A range's label in the box menu: a whitespace-collapsed snippet of its
     * text (or its offsets, for an insertion point), so picking a target
     * doesn't require memorizing offsets.
     */
    private fun rangeMenuLabel(range: TextRange): String {
        if (range.isPoint) {
            return "Insertion point @ ${range.start}"
        }
        val doc = editorHalf.bodyEditor.document
        val bodyStart = editorHalf.bodyStartOffset
        val start = (range.start + bodyStart).coerceIn(0, doc.textLength)
        val end = (range.end + bodyStart).coerceIn(start, doc.textLength)
        val snippet = doc.getText(com.intellij.openapi.util.TextRange(start, end))
            .replace(Regex("\\s+"), " ").trim()
        if (snippet.isEmpty()) {
            return "Range ${range.start}–${range.end} (${range.length} chars)"
        }
        val clipped = if (snippet.length > SNIPPET_MAX_CHARS) snippet.take(SNIPPET_MAX_CHARS) + "…" else snippet
        return "“$clipped”"
    }

    // ---- OCR ---------------------------------------------------------------

    /**
     * Discovers the site's OCR backends and their engines once, off the
     * EDT; no backends = no menu items. The engine/model half is not used
     * by this editor — it is published to [OcrCatalogService] so that the
     * favourites settings page, which has no page path of its own to
     * discover from, has real engines and languages to offer.
     */
    private fun loadOcrBackends() {
        val vfsPath = (file as? WtVirtualFile)?.path ?: return
        org.limepepper.lang.wikitext.vfs.settings.OcrCatalogService
            .getInstance(project)
            .discoverAsync(vfsPath) { backends, _ -> ocrBackends = backends }
    }

    /** Opens Settings > Tools > OCR Favourites. */
    private fun configureOcrFavorites() {
        com.intellij.openapi.options.ShowSettingsUtil.getInstance().showSettingsDialog(
            project,
            org.limepepper.lang.wikitext.vfs.settings.OcrFavoritesConfigurable::class.java,
        )
    }

    /**
     * Sends [box] to [backendInfo] through the sidecar wrapper and presents
     * the response for review. The cropped segment is captured on the EDT
     * (the canvas owns the decoded scan), encoded and sent on a pooled
     * thread, and the resulting [org.limepepper.lang.wikitext.ocr.OcrProposal]
     * lands in the OCR tool window — nothing touches the transcription until
     * the user applies it there.
     */
    private fun runOcr(
        box: org.limepepper.lang.wikitext.annotation.BoundingBox,
        choice: OcrMenuChoice,
    ) {
        val vfsPath = (file as? WtVirtualFile)?.path ?: return
        val backendInfo = choice.backend
        val segment = if (backendInfo.supportsSegment) {
            previewHalf.referenceImagePane.cropBoxImage(box)
        } else {
            null
        }
        ApplicationManager.getApplication().executeOnPooledThread {
            val proposal = try {
                val imageBase64 = segment?.let { img ->
                    val bytes = java.io.ByteArrayOutputStream()
                    javax.imageio.ImageIO.write(img, "png", bytes)
                    java.util.Base64.getEncoder().encodeToString(bytes.toByteArray())
                }
                // A favourite carries the engine/languages the user picked;
                // without one, every field stays unset so the sidecar fills
                // it from the backend's own configured defaults.
                val request = choice.favorite?.toRunRequest(
                    backendName = backendInfo.name,
                    annotationId = box.id,
                    boxX = box.x,
                    boxY = box.y,
                    boxWidth = box.width,
                    boxHeight = box.height,
                    imageBase64 = imageBase64,
                ) ?: org.limepepper.lang.wikitext.vfs.backend.OcrRunRequest(
                    backend = backendInfo.name,
                    annotationId = box.id,
                    boxX = box.x,
                    boxY = box.y,
                    boxWidth = box.width,
                    boxHeight = box.height,
                    imageBase64 = imageBase64,
                )
                val result = WtVfsService.instance.backend.runOcr(vfsPath, request)
                org.limepepper.lang.wikitext.ocr.OcrProposal(
                    title = "${file.name} · ${box.label ?: box.id.take(8)}",
                    pagePath = vfsPath,
                    boxId = box.id,
                    backend = result.backend,
                    engine = result.engine,
                    text = result.decodeText(),
                    applyToTarget = { text -> applyOcrText(box.id, text) },
                )
            } catch (e: Exception) {
                PRP_LOG.warn("OCR run failed for $vfsPath box ${box.id} via ${choice.label}", e)
                org.limepepper.lang.wikitext.ocr.OcrProposal(
                    title = "OCR failed · ${file.name}",
                    pagePath = vfsPath,
                    boxId = box.id,
                    backend = backendInfo.name,
                    engine = choice.engine,
                    text = "OCR request failed: ${e.message ?: e.javaClass.simpleName}",
                )
            }
            ApplicationManager.getApplication().invokeLater {
                if (!disposed) {
                    org.limepepper.lang.wikitext.ocr.OcrReviewController
                        .getInstance(project)
                        .present(proposal)
                }
            }
        }
    }

    /**
     * The accept path: replaces the content of the box's linked text range
     * with [text] (an insertion point receives it as an insert). Offsets go
     * through the live range model, so edits made since the OCR ran are
     * respected. Returns a user-facing error, or null on success.
     */
    private fun applyOcrText(boxId: String, text: String): String? {
        val rangeId = linkModel.rangeFor(boxId)
            ?: return "This box has no linked text range — link one first."
        val range = rangeModel[rangeId]
            ?: return "The linked text range no longer exists."
        val editor = editorHalf.bodyEditor
        if (editor.isDisposed) {
            return "The editor for this page is closed."
        }
        val doc = editor.document
        val bodyStart = editorHalf.bodyStartOffset
        val start = (range.start + bodyStart).coerceIn(0, doc.textLength)
        val end = (range.end + bodyStart).coerceIn(start, doc.textLength)
        com.intellij.openapi.command.WriteCommandAction.runWriteCommandAction(project) {
            doc.replaceString(start, end, text)
        }
        rangeModel.select(rangeId)
        anchorManager.reveal(rangeId)
        return null
    }

    /** Loads persisted text ranges + box links off the EDT, then seeds models + syncs. */
    private fun loadTextRanges(model: TextRangeModel, linkModel: BoxLinkModel) {
        val vfsPath = (file as? WtVirtualFile)?.path ?: return
        ApplicationManager.getApplication().executeOnPooledThread {
            val backend = WtVfsService.instance.backend
            val loaded = try {
                backend.listTextAnchors(vfsPath).map {
                    TextRange(id = it.annotationId, start = it.textStart, end = it.textEnd, anchorRevid = it.anchorRevid)
                }
            } catch (e: Exception) {
                PRP_LOG.warn("text-range load failed for $vfsPath", e)
                null
            }
            val links = if (loaded == null) {
                null
            } else {
                try {
                    backend.listBoxLinks(vfsPath).associate { it.boxId to it.rangeId }
                } catch (e: Exception) {
                    PRP_LOG.warn("box-link load failed for $vfsPath", e)
                    null
                }
            }
            ApplicationManager.getApplication().invokeLater {
                if (disposed || loaded == null) {
                    return@invokeLater
                }
                model.setAll(loaded)
                val sync = WtTextRangeSync(model, vfsPath)
                Disposer.register(this, sync)
                sync.seed(loaded)
                if (links != null) {
                    // Defensive prune: a persisted link whose range didn't
                    // load is already invalid. Seeding the sync with the raw
                    // server state makes its first flush delete those rows.
                    val valid = loaded.mapTo(HashSet()) { it.id }
                    linkModel.setAll(links.filterValues { it in valid })
                    val linkSync = WtBoxLinkSync(linkModel, vfsPath)
                    Disposer.register(this, linkSync)
                    linkSync.seed(links)
                }
            }
        }
    }

    override fun dispose() {
        disposed = true
        super.dispose()
    }

    /** The pane whose structure the tool window should currently show. */
    fun activePane(): ActivePane {
        val previewActive = when (getLayout()) {
            Layout.SHOW_PREVIEW -> true
            Layout.SHOW_EDITOR -> false
            else -> previewFocused
        }
        if (!previewActive) {
            return ActivePane.EDITOR
        }
        return when (previewHalf.activePreviewKind()) {
            PrpPreviewBrowser.PaneKind.IMAGE -> ActivePane.PREVIEW_IMAGE
            PrpPreviewBrowser.PaneKind.RENDER -> ActivePane.PREVIEW_RENDER
        }
    }

    override fun getStructureViewBuilder(): StructureViewBuilder =
        PrpStructureViewBuilder(editorHalf, previewHalf, ::activePane, ::navigateToBox)

    override fun onLayoutChange(oldValue: Layout?, newValue: Layout?) {
        super.onLayoutChange(oldValue, newValue)
        refreshStructureView()
    }

    /**
     * Reveals [box] on the scan and, when it carries a text anchor, jumps the
     * transcription caret to the linked region — the same mapping the anchor
     * chrome uses (offsets are body-relative, see [PrpTextEditor.bodyStartOffset]).
     */
    private fun navigateToBox(box: BoundingBox) {
        previewHalf.revealImagePane()
        previewHalf.referenceImagePane.revealBox(box.id)
        linkModel.rangeFor(box.id)?.let { rangeId ->
            if (rangeModel[rangeId] != null) {
                rangeModel.select(rangeId)
                anchorManager.reveal(rangeId)
            }
        }
    }

    /**
     * Asks the Structure tool window to re-query [getStructureViewBuilder]. The
     * window only rebuilds on file/selection changes on its own, and switching
     * panes here changes neither, so nudge it explicitly. Same broadcast the
     * bundled JSON/YAML/XML structure factories use.
     */
    private fun refreshStructureView() {
        ApplicationManager.getApplication().messageBus
            .syncPublisher(StructureViewWrapperImpl.STRUCTURE_CHANGED)
            .run()
    }

    private companion object {
        const val SNIPPET_MAX_CHARS = 40
    }
}
