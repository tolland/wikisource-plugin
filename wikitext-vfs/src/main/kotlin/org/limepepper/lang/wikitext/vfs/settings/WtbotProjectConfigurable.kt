package org.limepepper.lang.wikitext.vfs.settings

import com.intellij.openapi.options.SearchableConfigurable
import com.intellij.openapi.project.Project
import javax.swing.*
import java.awt.GridBagLayout
import java.awt.GridBagConstraints
import java.awt.Insets

class WtbotProjectConfigurable(private val project: Project) : SearchableConfigurable {
    private var panel: JPanel? = null
    private var hostField: JTextField? = null
    private var portField: JTextField? = null
    private var timeoutField: JTextField? = null

    override fun getId(): String = "org.limepepper.wikitext.wtbot.project"
    override fun getDisplayName(): String = "WTBot (VFS backend)"

    override fun createComponent(): JComponent {
        if (panel == null) {
            panel = JPanel(GridBagLayout())
            val c = GridBagConstraints().apply {
                gridx = 0; gridy = 0
                anchor = GridBagConstraints.WEST
                insets = Insets(4, 4, 4, 4)
            }

            panel!!.add(JLabel("Host:"), c)
            hostField = JTextField(20)
            c.gridx = 1; panel!!.add(hostField, c)

            c.gridx = 0; c.gridy = 1
            panel!!.add(JLabel("Port:"), c)
            portField = JTextField(6)
            c.gridx = 1; panel!!.add(portField, c)

            c.gridx = 0; c.gridy = 2
            panel!!.add(JLabel("Timeout (s):"), c)
            timeoutField = JTextField(6)
            c.gridx = 1; panel!!.add(timeoutField, c)

            reset()
        }
        return panel!!
    }

    override fun isModified(): Boolean {
        val s = WtbotProjectSettings.getInstance(project)
        val hostMod = hostField?.text != s.host
        val portMod = try { portField?.text?.toInt() != s.port } catch (e: Exception) { true }
        val timeoutMod = try { timeoutField?.text?.toInt() != s.timeoutSeconds } catch (e: Exception) { true }
        return hostMod || portMod || timeoutMod
    }

    override fun apply() {
        val s = WtbotProjectSettings.getInstance(project)
        val hostText = hostField?.text?.trim().orEmpty()
        val portInt = try { portField?.text?.trim()?.toInt() ?: s.port } catch (e: Exception) { s.port }
        val timeoutInt = try { timeoutField?.text?.trim()?.toInt() ?: s.timeoutSeconds } catch (e: Exception) { s.timeoutSeconds }

        s.host = hostText
        s.port = portInt
        s.timeoutSeconds = timeoutInt
    }

    override fun reset() {
        val s = WtbotProjectSettings.getInstance(project)
        hostField?.text = s.host
        portField?.text = s.port.toString()
        timeoutField?.text = s.timeoutSeconds.toString()
    }

    override fun disposeUIResources() {
        panel = null
        hostField = null
        portField = null
        timeoutField = null
    }
}
