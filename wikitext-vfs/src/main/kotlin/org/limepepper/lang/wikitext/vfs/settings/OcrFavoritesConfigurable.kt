package org.limepepper.lang.wikitext.vfs.settings

import com.intellij.openapi.options.SearchableConfigurable
import com.intellij.openapi.project.Project
import com.intellij.ui.CollectionListModel
import com.intellij.ui.SimpleListCellRenderer
import com.intellij.ui.ToolbarDecorator
import com.intellij.ui.components.JBLabel
import com.intellij.ui.components.JBList
import java.awt.BorderLayout
import javax.swing.JCheckBox
import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.ListSelectionModel

/**
 * Settings > Tools > OCR Favourites — the small, ordered list of
 * engine/language combinations the reference image's "Run OCR" menu
 * offers.
 *
 * The list is short by design and its order is the menu order, so the
 * toolbar carries move-up/move-down as well as add/edit/remove.
 *
 * One list, two stores: "Use project-specific favourites" chooses which
 * one it is editing — the project's own ([OcrFavoritesProjectSettings]) or
 * the application-wide defaults ([OcrFavoritesAppSettings]) every other
 * project inherits. A separate application-level page would have been the
 * other way to reach those defaults, but it would show the same widget
 * twice and leave the reader guessing which one their menu came from;
 * here, what is on screen is always what this project will get.
 */
class OcrFavoritesConfigurable(private val project: Project) : SearchableConfigurable {

    private var panel: JPanel? = null
    // CollectionListModel rather than DefaultListModel: it implements
    // EditableModel, which is what makes ToolbarDecorator's move up/down
    // buttons functional — and order is menu order here, so they matter.
    private val listModel = CollectionListModel<OcrFavorite>()
    private val list = JBList(listModel).apply {
        selectionMode = ListSelectionModel.SINGLE_SELECTION
        cellRenderer = SimpleListCellRenderer.create<OcrFavorite> { label, value, _ ->
            label.text = value?.displayName().orEmpty()
        }
    }
    private val useProjectBox = JCheckBox("Use project-specific favourites")
    private val hint = JBLabel()

    override fun getId(): String = "org.limepepper.wikitext.ocr.favorites"

    override fun getDisplayName(): String = "OCR Favourites"

    override fun createComponent(): JComponent {
        if (panel == null) {
            useProjectBox.addActionListener { onScopeToggled() }
            val decorated = ToolbarDecorator.createDecorator(list)
                .setAddAction { addFavorite() }
                .setEditAction { editSelected() }
                .setRemoveAction { removeSelected() }
                .setMoveUpAction { move(-1) }
                .setMoveDownAction { move(1) }
                .createPanel()
            panel = JPanel(BorderLayout(0, 8)).apply {
                add(
                    JPanel(BorderLayout()).apply {
                        add(useProjectBox, BorderLayout.NORTH)
                        add(hint, BorderLayout.SOUTH)
                    },
                    BorderLayout.NORTH,
                )
                add(decorated, BorderLayout.CENTER)
            }
            reset()
        }
        return panel!!
    }

    /**
     * Ticking on keeps whatever is on screen — which is the application
     * defaults — as the project's starting point, since the common edit is
     * "the usual set, plus Latin" and retyping the usual set first would be
     * a poor trade. Ticking off discards the project list and shows the
     * application defaults, which is now what the menu will use.
     */
    private fun onScopeToggled() {
        if (!useProjectBox.isSelected) {
            load(OcrFavoritesAppSettings.getInstance().favorites)
        }
        updateHint()
    }

    private fun updateHint() {
        hint.text = if (useProjectBox.isSelected) {
            "Editing this project's favourites."
        } else {
            "Editing the application defaults, used by every project that has no list of " +
                "its own. Tick the box above to give this project a separate list instead."
        }
    }

    private fun currentCatalog() = OcrCatalogService.getInstance(project)

    private fun addFavorite() {
        val service = currentCatalog()
        val dialog = OcrFavoriteDialog(
            service.cachedCatalog(),
            service.cachedBackends().map { it.name },
        )
        if (dialog.showAndGet()) {
            listModel.add(dialog.result())
            list.selectedIndex = listModel.size - 1
        }
    }

    private fun editSelected() {
        val index = list.selectedIndex
        if (index < 0) return
        val service = currentCatalog()
        val dialog = OcrFavoriteDialog(
            service.cachedCatalog(),
            service.cachedBackends().map { it.name },
            listModel.getElementAt(index),
        )
        if (dialog.showAndGet()) {
            listModel.setElementAt(dialog.result(), index)
        }
    }

    private fun removeSelected() {
        val index = list.selectedIndex
        if (index >= 0) {
            listModel.remove(index)
            list.selectedIndex = (index - 1).coerceAtLeast(0)
        }
    }

    private fun move(delta: Int) {
        val from = list.selectedIndex
        val to = from + delta
        if (from < 0 || to < 0 || to >= listModel.size) return
        listModel.exchangeRows(from, to)
        list.selectedIndex = to
    }

    private fun load(favorites: List<OcrFavorite>) {
        listModel.replaceAll(favorites.map { it.copy() })
    }

    private fun currentFavorites(): List<OcrFavorite> = listModel.items.toList()

    override fun isModified(): Boolean {
        val settings = OcrFavoritesProjectSettings.getInstance(project)
        if (useProjectBox.isSelected != settings.useProjectFavorites) return true
        val stored =
            if (useProjectBox.isSelected) settings.favorites
            else OcrFavoritesAppSettings.getInstance().favorites
        return currentFavorites() != stored
    }

    override fun apply() {
        val settings = OcrFavoritesProjectSettings.getInstance(project)
        if (useProjectBox.isSelected) {
            settings.favorites = currentFavorites()
        } else {
            OcrFavoritesAppSettings.getInstance().favorites = currentFavorites()
        }
        settings.useProjectFavorites = useProjectBox.isSelected
        // No change notification needed: the popup asks for the effective
        // list every time it is built, so the next right-click sees this.
    }

    override fun reset() {
        val settings = OcrFavoritesProjectSettings.getInstance(project)
        useProjectBox.isSelected = settings.useProjectFavorites
        load(settings.effectiveFavorites())
        updateHint()
    }

    override fun disposeUIResources() {
        panel = null
    }
}
