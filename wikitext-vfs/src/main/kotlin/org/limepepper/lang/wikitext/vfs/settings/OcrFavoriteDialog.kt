package org.limepepper.lang.wikitext.vfs.settings

import com.intellij.openapi.ui.DialogWrapper
import com.intellij.openapi.ui.ValidationInfo
import org.limepepper.lang.wikitext.vfs.backend.OcrCatalog
import java.awt.BorderLayout
import java.awt.Dimension
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import java.awt.Insets
import javax.swing.DefaultListModel
import javax.swing.JComboBox
import javax.swing.JComponent
import javax.swing.JLabel
import javax.swing.JList
import javax.swing.JPanel
import javax.swing.JScrollPane
import javax.swing.JTextField
import javax.swing.ListSelectionModel

/**
 * The add/edit form for one [OcrFavorite].
 *
 * Both pickers are editable combo boxes rather than plain dropdowns: they
 * are populated from whatever a page editor last discovered
 * ([OcrCatalogService]), which may be nothing at all if the settings page
 * is opened before any page has been, and a favourite typed by hand has to
 * keep working in that case.
 *
 * The language list is a multi-select over the *selected engine's* models
 * only — the whole point of favourites is that the full cross-product is
 * unusable, and offering Google's hundreds of languages under an engine
 * that cannot recognize them would just recreate the problem inside the
 * settings dialog.
 */
class OcrFavoriteDialog(
    private val catalog: OcrCatalog,
    private val backendNames: List<String>,
    private val initial: OcrFavorite? = null,
) : DialogWrapper(true) {

    private val engineField = JComboBox<String>().apply {
        isEditable = true
        catalog.engines.forEach { addItem(it.engine) }
    }
    private val backendField = JComboBox<String>().apply {
        isEditable = true
        addItem("") // "whichever the site lists first"
        backendNames.forEach { addItem(it) }
    }
    private val langsModel = DefaultListModel<String>()
    private val langsList = JList(langsModel).apply {
        selectionMode = ListSelectionModel.MULTIPLE_INTERVAL_SELECTION
        visibleRowCount = 8
    }
    private val extraLangsField = JTextField(20)
    private val labelField = JTextField(20)
    private val promptField = JTextField(20)

    /** The engine whose models [langsModel] currently holds. */
    private var loadedEngine: String? = null

    init {
        title = if (initial == null) "Add OCR Favourite" else "Edit OCR Favourite"
        engineField.addActionListener { reloadLanguages() }
        initial?.let { favorite ->
            engineField.selectedItem = favorite.engine
            backendField.selectedItem = favorite.backend.orEmpty()
            labelField.text = favorite.label.orEmpty()
            promptField.text = favorite.prompt.orEmpty()
        }
        reloadLanguages()
        initial?.let { selectLanguages(it.langs) }
        init()
    }

    /**
     * Repopulates the language list for the engine now selected, keeping
     * any codes that survive the switch selected. Codes the new engine
     * doesn't offer stay in the free-text field instead of vanishing —
     * silently dropping a language on an engine change would be a nasty
     * surprise.
     */
    private fun reloadLanguages() {
        val previouslySelected = selectedLanguages()
        val engine = currentEngine()
        val models = catalog.engine(engine)?.models.orEmpty()
        langsModel.clear()
        models.forEach { langsModel.addElement(it.displayName) }
        // Only now is the list the new engine's; everything above still had
        // to read the old one's.
        loadedEngine = engine
        if (previouslySelected.isNotEmpty()) {
            selectLanguages(previouslySelected)
        }
    }

    private fun selectLanguages(codes: List<String>) {
        val wanted = codes.toMutableSet()
        val indices = mutableListOf<Int>()
        loadedModels().forEachIndexed { index, model ->
            if (wanted.remove(model.code)) indices += index
        }
        langsList.selectedIndices = indices.toIntArray()
        // Whatever the engine doesn't offer stays editable as free text.
        extraLangsField.text = wanted.joinToString(", ")
    }

    private fun currentEngine(): String = (engineField.editor.item ?: "").toString().trim()

    /**
     * The models the language list is *currently showing*, which is not
     * [currentEngine]'s during an engine switch — the combo box has already
     * changed by the time its listener runs, so reading the selection
     * against the new engine would map the old indices onto the wrong codes.
     */
    private fun loadedModels() = loadedEngine?.let { catalog.engine(it)?.models }.orEmpty()

    private fun selectedLanguages(): List<String> {
        val models = loadedModels()
        // toList() first: selectedIndices is an IntArray, which has no
        // mapNotNull of its own.
        val fromList = langsList.selectedIndices.toList().mapNotNull { models.getOrNull(it)?.code }
        val fromField = extraLangsField.text
            .split(',')
            .map { it.trim() }
            .filter { it.isNotEmpty() }
        return (fromList + fromField).distinct()
    }

    override fun createCenterPanel(): JComponent {
        val panel = JPanel(GridBagLayout())
        val c = GridBagConstraints().apply {
            gridx = 0
            gridy = 0
            anchor = GridBagConstraints.WEST
            insets = Insets(4, 4, 4, 4)
        }

        fun row(label: String, field: JComponent) {
            c.gridx = 0
            c.fill = GridBagConstraints.NONE
            c.weightx = 0.0
            panel.add(JLabel(label), c)
            c.gridx = 1
            c.fill = GridBagConstraints.HORIZONTAL
            c.weightx = 1.0
            panel.add(field, c)
            c.gridy++
        }

        row("Engine:", engineField)
        row("Backend:", backendField)

        c.gridx = 0
        c.fill = GridBagConstraints.NONE
        c.weightx = 0.0
        c.anchor = GridBagConstraints.NORTHWEST
        panel.add(JLabel("Languages:"), c)
        c.gridx = 1
        c.fill = GridBagConstraints.BOTH
        c.weightx = 1.0
        c.weighty = 1.0
        val languages = JPanel(BorderLayout(0, 4)).apply {
            add(JScrollPane(langsList).apply { preferredSize = Dimension(320, 160) }, BorderLayout.CENTER)
            add(
                JPanel(BorderLayout(4, 0)).apply {
                    add(JLabel("Other codes:"), BorderLayout.WEST)
                    add(extraLangsField, BorderLayout.CENTER)
                },
                BorderLayout.SOUTH,
            )
        }
        panel.add(languages, c)
        c.gridy++
        c.weighty = 0.0
        c.anchor = GridBagConstraints.WEST

        row("Menu label:", labelField)
        row("Prompt:", promptField)

        c.gridx = 0
        c.gridwidth = 2
        panel.add(
            JLabel(
                "<html><small>Leave the backend blank to use the site's first configured " +
                    "backend, and the languages empty to use its defaults — which is what " +
                    "an engine with no language dimension (pix2tex) wants. The prompt is " +
                    "ignored by engines that don't read one.</small></html>"
            ),
            c,
        )
        return panel
    }

    override fun doValidate(): ValidationInfo? =
        if (currentEngine().isBlank()) ValidationInfo("An engine is required", engineField)
        else null

    override fun getPreferredFocusedComponent(): JComponent = engineField

    /** The edited favourite. Only valid after the dialog was accepted. */
    fun result(): OcrFavorite = OcrFavorite(
        engine = currentEngine(),
        langs = selectedLanguages(),
        backend = (backendField.editor.item ?: "").toString().trim().takeIf { it.isNotEmpty() },
        label = labelField.text.trim().takeIf { it.isNotEmpty() },
        prompt = promptField.text.trim().takeIf { it.isNotEmpty() },
    )
}
