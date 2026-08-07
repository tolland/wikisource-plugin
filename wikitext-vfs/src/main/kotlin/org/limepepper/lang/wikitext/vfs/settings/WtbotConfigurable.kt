package org.limepepper.lang.wikitext.vfs.settings

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.options.ConfigurationException
import com.intellij.openapi.options.SearchableConfigurable
import org.limepepper.lang.wikitext.vfs.backend.WtBackendSwitcher
import java.awt.GridBagConstraints
import java.awt.GridBagLayout
import java.awt.Insets
import java.net.URI
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.time.Duration
import javax.swing.JButton
import javax.swing.JComponent
import javax.swing.JLabel
import javax.swing.JPanel
import javax.swing.JTextField
import javax.swing.SwingUtilities

/**
 * Settings page for the wtbot sidecar the `wikisource://` VFS talks to.
 *
 * Application-scoped: one sidecar serves every project (it is the thing that
 * mediates between wikis), and the VFS it feeds is an application singleton.
 *
 * Applying a new base URL switches the live backend immediately — no restart —
 * which is the point: development means moving between a workstation sidecar
 * and the docker harness without losing the IDE session.
 */
class WtbotConfigurable : SearchableConfigurable {

    private var panel: JPanel? = null
    private var baseUrlField: JTextField? = null
    private var timeoutField: JTextField? = null
    private var statusLabel: JLabel? = null

    override fun getId(): String = "org.limepepper.wikitext.wtbot"

    override fun getDisplayName(): String = "WTBot (VFS backend)"

    override fun createComponent(): JComponent {
        if (panel == null) {
            val created = JPanel(GridBagLayout())
            val c = GridBagConstraints().apply {
                gridx = 0
                gridy = 0
                anchor = GridBagConstraints.WEST
                insets = Insets(4, 4, 4, 4)
            }

            created.add(JLabel("Base URL:"), c)
            baseUrlField = JTextField(30)
            c.gridx = 1
            created.add(baseUrlField, c)

            c.gridx = 0; c.gridy = 1
            created.add(JLabel("Timeout (s):"), c)
            timeoutField = JTextField(6)
            c.gridx = 1
            created.add(timeoutField, c)

            c.gridx = 1; c.gridy = 2
            created.add(JButton("Test Connection").apply { addActionListener { testConnection() } }, c)

            c.gridx = 1; c.gridy = 3
            statusLabel = JLabel(" ")
            created.add(statusLabel, c)

            panel = created
            reset()
        }
        return panel!!
    }

    override fun isModified(): Boolean {
        val settings = WtbotAppSettings.getInstance()
        val urlModified = baseUrlField?.text?.trim() != settings.baseUrl
        val timeoutModified = timeoutField?.text?.trim()?.toIntOrNull() != settings.timeoutSeconds
        return urlModified || timeoutModified
    }

    override fun apply() {
        val settings = WtbotAppSettings.getInstance()
        val rawUrl = baseUrlField?.text?.trim().orEmpty()
        val baseUrl = WtbotAppSettings.normalizeBaseUrl(rawUrl)
            ?: throw ConfigurationException(
                "'$rawUrl' is not a usable wtbot base URL — expected something like " +
                    "${WtbotAppSettings.DEFAULT_BASE_URL}",
            )
        val timeout = timeoutField?.text?.trim()?.toIntOrNull()
            ?: throw ConfigurationException("Timeout must be a whole number of seconds")
        if (timeout !in WtbotAppSettings.TIMEOUT_RANGE) {
            throw ConfigurationException(
                "Timeout must be between ${WtbotAppSettings.TIMEOUT_RANGE.first} and " +
                    "${WtbotAppSettings.TIMEOUT_RANGE.last} seconds",
            )
        }

        // Ask about unsaved wikisource edits while the old backend is still
        // the one they belong to. Cancelling puts the fields back rather than
        // raising an error — the user chose not to switch, which isn't a
        // misconfiguration.
        if (baseUrl != settings.baseUrl && !WtBackendSwitcher.confirmPendingEdits()) {
            reset()
            return
        }

        settings.update(baseUrl, timeout)
    }

    override fun reset() {
        val settings = WtbotAppSettings.getInstance()
        baseUrlField?.text = settings.baseUrl
        timeoutField?.text = settings.timeoutSeconds.toString()
        statusLabel?.text = " "
    }

    override fun disposeUIResources() {
        panel = null
        baseUrlField = null
        timeoutField = null
        statusLabel = null
    }

    /**
     * Probes the URL currently typed in the field — not the saved one — so a
     * sidecar can be confirmed reachable before Apply switches the VFS onto it.
     */
    private fun testConnection() {
        val rawUrl = baseUrlField?.text?.trim().orEmpty()
        val baseUrl = WtbotAppSettings.normalizeBaseUrl(rawUrl)
        if (baseUrl == null) {
            statusLabel?.text = "✗ not a usable URL"
            return
        }
        statusLabel?.text = "checking…"
        ApplicationManager.getApplication().executeOnPooledThread {
            val result = probeHealth(baseUrl)
            SwingUtilities.invokeLater { statusLabel?.text = result }
        }
    }

    private fun probeHealth(baseUrl: String): String = try {
        val client = HttpClient.newBuilder().connectTimeout(PROBE_TIMEOUT).build()
        val request = HttpRequest.newBuilder(URI.create("$baseUrl/health"))
            .timeout(PROBE_TIMEOUT)
            .version(HttpClient.Version.HTTP_1_1)
            .GET()
            .build()
        val response = client.send(request, HttpResponse.BodyHandlers.ofString())
        if (response.statusCode() in 200..299) "✓ sidecar responded" else "✗ HTTP ${response.statusCode()}"
    } catch (e: Exception) {
        "✗ ${e.message ?: e.javaClass.simpleName}"
    }

    private companion object {
        private val PROBE_TIMEOUT: Duration = Duration.ofSeconds(5)
    }
}
