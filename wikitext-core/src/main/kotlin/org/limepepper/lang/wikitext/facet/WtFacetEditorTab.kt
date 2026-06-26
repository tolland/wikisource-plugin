package org.limepepper.lang.wikitext.facet

import com.intellij.facet.ui.FacetEditorContext
import com.intellij.facet.ui.FacetEditorTab
import com.intellij.facet.ui.FacetValidatorsManager
import com.intellij.openapi.options.ConfigurationException
import com.intellij.openapi.util.text.StringUtil
import org.jetbrains.annotations.Nls
import java.awt.BorderLayout
import javax.swing.JComponent
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.JTextField


/**
 * Provides the JPanel to be displayed in the facet UI.
 * Manages validation and modification of the [WtFacet] state.
 */
class WtFacetEditorTab(
    state: WtFacetState, context: FacetEditorContext?,
    validator: FacetValidatorsManager?
) : FacetEditorTab() {
    private val mySettings: WtFacetState
    private val myPath: JTextField

    /**
     * Only org.intellij.sdk.facet.DemoFacetState is captured so it can be updated per user changes in the EditorTab.
     *
     * @param state     [WtFacetState] object persisting [WtFacet] state.
     * @param context   Facet editor context, can be used to get e.g. the current project module.
     * @param validator Facet validator manager, can be used to get and apply a custom validator for this facet.
     */
    init {
        mySettings = state
        myPath = JTextField(state.wtFacetState)
    }

    /**
     * Provides the [JPanel] displayed in the Project Structure | Facet UI
     *
     * @return [JPanel] to be displayed in the [DemoFacetEditorTab].
     */
    override fun createComponent(): JComponent {
        val top = JPanel(BorderLayout())
        top.add(JLabel(FACET_PANEL_PROMPT), BorderLayout.WEST)
        top.add(myPath)
        val facetPanel = JPanel(BorderLayout())
        facetPanel.add(top, BorderLayout.NORTH)
        return facetPanel
    }

    /**
     * @return the name of this facet for display in this editor tab.
     */
    @Nls(capitalization = Nls.Capitalization.Title)
    override fun getDisplayName(): String {
        return WtFacetType.FACET_NAME
    }

    /**
     * Determines if the facet state entered in the UI differs from the currently stored state.
     * Called when user changes text in [.myPath].
     *
     * @return `true` if the state returned from the panel's UI differs from the stored facet state.
     */
    override fun isModified(): Boolean {
        return !StringUtil.equals(mySettings.wtFacetState, myPath.getText().trim { it <= ' ' })
    }

    /**
     * Stores new facet state (text) entered by the user.
     * Called when [.isModified] returns true.
     *
     * @throws ConfigurationException if anything generates an exception.
     */
    @Throws(ConfigurationException::class)
    override fun apply() {
        // Not much to go wrong here, but fulfill the contract
        try {
            val newTextContent = myPath.getText()
            mySettings.wtFacetState = newTextContent
        } catch (e: Exception) {
            throw ConfigurationException(e.toString())
        }
    }

    /**
     * Copies current [DemoFacetState] into the [.myPath] UI element.
     * This method is called each time this editor tab is needed for display.
     */
    override fun reset() {
        myPath.setText(mySettings.wtFacetState)
    }

    companion object {
        private const val FACET_PANEL_PROMPT = "Path To SDK: "
    }
}