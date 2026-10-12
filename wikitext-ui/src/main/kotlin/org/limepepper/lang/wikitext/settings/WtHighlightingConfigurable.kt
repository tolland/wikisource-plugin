package org.limepepper.lang.wikitext.settings

import com.intellij.openapi.options.SearchableConfigurable
import com.intellij.ui.components.JBCheckBox
import com.intellij.ui.components.JBLabel
import java.awt.BorderLayout
import java.util.Hashtable
import javax.swing.BoxLayout
import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.JSlider

class WtHighlightingConfigurable : SearchableConfigurable {
    private var panel: JPanel? = null
    private var enabled: JBCheckBox? = null
    private var references: JBCheckBox? = null
    private var strength: JSlider? = null
    private var valueLabel: JBLabel? = null

    override fun getId(): String = "org.limepepper.wikitext.highlighting"
    override fun getDisplayName(): String = "Wikitext Highlighting"

    override fun createComponent(): JComponent {
        panel?.let { return it }
        val referenceBox = JBCheckBox("Distinguish reference content from document text")
        references = referenceBox
        val enabledBox = JBCheckBox("Enable sentence and clause bands")
        val strengthSlider = JSlider(0, 100).apply {
            majorTickSpacing = 25
            paintTicks = true
            paintLabels = true
            labelTable = Hashtable<Int, JComponent>().apply {
                put(0, JBLabel("Off"))
                put(12, JBLabel("Quiet"))
                put(100, JBLabel("Strong"))
            }
            accessibleContext.accessibleName = "Band strength"
        }
        val valueLabel = JBLabel()
        enabledBox.addActionListener { updateControls() }
        strengthSlider.addChangeListener { updateControls() }
        enabled = enabledBox
        strength = strengthSlider
        this.valueLabel = valueLabel
        val controls = JPanel().apply {
            layout = BoxLayout(this, BoxLayout.Y_AXIS)
            add(enabledBox)
            add(valueLabel)
            add(strengthSlider)
            add(referenceBox)
            add(JBLabel("Disable both options to compare normal syntax highlighting. Changes take effect on Apply."))
        }
        return JPanel(BorderLayout()).apply {
            add(controls, BorderLayout.NORTH)
            panel = this
            reset()
            updateControls()
        }
    }

    private fun selectedOptions() = WtHighlightingSettings.Options(
        bandsEnabled = enabled!!.isSelected,
        bandStrength = strength!!.value,
        referencesEnabled = references!!.isSelected,
    )

    override fun isModified(): Boolean =
        panel != null && selectedOptions() != WtHighlightingSettings.getInstance().state

    override fun apply() {
        if (panel != null) WtHighlightingSettings.getInstance().update(selectedOptions())
    }

    override fun reset() {
        val options = WtHighlightingSettings.getInstance().state
        enabled?.isSelected = options.bandsEnabled
        strength?.value = options.bandStrength
        references?.isSelected = options.referencesEnabled
        updateControls()
    }

    private fun updateControls() {
        val active = enabled?.isSelected == true
        strength?.isEnabled = active
        valueLabel?.text = "Band strength: ${strength?.value ?: 0}%"
        valueLabel?.isEnabled = active
    }

    override fun disposeUIResources() {
        panel = null
        enabled = null
        references = null
        strength = null
        valueLabel = null
    }
}
