package org.limepepper.lang.wikitext

import com.intellij.driver.client.Driver
import com.intellij.driver.client.service
import com.intellij.driver.model.OnDispatcher
import com.intellij.driver.sdk.*
import com.intellij.driver.sdk.ui.components.UiComponent
import com.intellij.driver.sdk.ui.components.elements.button
import com.intellij.driver.sdk.ui.components.elements.contentTabLabel
import com.intellij.driver.sdk.ui.present
import com.intellij.driver.sdk.ui.shouldBe
import com.intellij.driver.sdk.ui.ui
import com.intellij.ide.starter.ci.CIServer
import com.intellij.ide.starter.ci.NoCIServer
import com.intellij.ide.starter.di.di
import com.intellij.ide.starter.driver.engine.runIdeWithDriver
import com.intellij.ide.starter.ide.installer.ExistingIdeInstaller
import com.intellij.ide.starter.models.IdeInfo
import com.intellij.ide.starter.models.TestCase
import com.intellij.ide.starter.plugins.PluginConfigurator
import com.intellij.ide.starter.project.LocalProjectInfo
import com.intellij.ide.starter.runner.Starter
import com.intellij.platform.testFramework.teamCity.TeamCityReporter.SyntheticTestKind
import com.intellij.tools.ide.starter.product.idea.ultimate.IdeaUltimate
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Tag
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.fail
import org.junit.jupiter.api.io.TempDir
import org.junit.jupiter.api.extension.RegisterExtension
import org.kodein.di.DI
import org.kodein.di.bindSingleton
import java.nio.file.Path
import kotlin.io.path.createDirectories
import kotlin.io.path.writeText
import kotlin.time.Duration.Companion.minutes
import kotlin.time.Duration.Companion.seconds

/** Starts a real IDE; deliberately independent of wtbot and MediaWiki. */
class PluginStartupTest {
    @JvmField
    @RegisterExtension
    val wtbot = WtbotServerExtension()

    init {
        // Outside TeamCity, Starter otherwise only logs IDE-process failures.
        di = DI {
            extend(di)
            bindSingleton<CIServer>(overrides = true) {
                object : CIServer by NoCIServer {
                    override fun reportTestFailure(
                        testName: String,
                        message: String,
                        details: String,
                        linkToLogs: String?,
                        kind: SyntheticTestKind,
                        generifyTestName: Boolean,
                    ) {
                        fail("$testName: $message\n$details")
                    }
                }
            }
        }
    }

    @Test
    fun projectProvidesEditorAndToolWindows(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-project-editor") { fixtureText ->
            assertTrue(isPluginLoaded("org.limepepper.lang.wikitext"), "Wikitext plugin must be loaded")

            openFile("sample.wiki")
            withContext(OnDispatcher.EDT) {
                val editor = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()) {
                    "The wikitext file must have a text editor"
                }
                assertEquals(fixtureText, editor.getDocument().getText())
                assertEquals("sample.wiki", editor.getVirtualFile().getName())
            }

            openToolWindow("Project")
            waitFor("Project tool window is visible", 30.seconds) {
                withContext(OnDispatcher.EDT) { getToolWindow("Project").isVisible() }
            }
            openToolWindow("Wikisource OCR")
            waitFor("Wikisource OCR tool window is visible", 30.seconds) {
                withContext(OnDispatcher.EDT) { getToolWindow("Wikisource OCR").isVisible() }
            }
        }

    @Test
    @Tag("extended")
    fun browserAndDebugTabsCanBeSwitched(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-tool-window-tabs") {
            openToolWindow("MyToolWindow")
            val window = wikisourceWindow()
            window.contentTabLabel("Debug").click()
            waitFor("Debug tab is selected", 30.seconds) { window.contentTabLabel("Debug").isSelected }
            window.button { byVisibleText("Refresh") }.shouldBe(present)
            window.contentTabLabel("Browser").click()
            waitFor("Browser tab is selected", 30.seconds) { window.contentTabLabel("Browser").isSelected }
            window.x { byType("javax.swing.JSplitPane") }.shouldBe(present)
        }

    @Test
    @Tag("extended")
    fun debugRefreshShowsBackendStatus(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-debug-refresh") {
            openToolWindow("MyToolWindow")
            val window = wikisourceWindow()
            window.contentTabLabel("Debug").click()
            window.button { byVisibleText("Refresh") }.click()
            // The sidecar is optional: both connected and offline are valid
            // results, but the endpoint and completed status must be visible.
            window.x {
                and(
                    byType("javax.swing.JLabel"),
                    contains(byVisibleText(requireNotNull(System.getProperty("wtbot.test.baseUrl")))),
                    or(contains(byVisibleText("Status: ✓")), contains(byVisibleText("Status: ✗"))),
                )
            }.shouldBe(present)
        }

    @Test
    @Tag("extended")
    fun reopeningToolWindowPreservesSelectedTab(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-tool-window-reopen") {
            openToolWindow("MyToolWindow")
            val window = wikisourceWindow()
            window.contentTabLabel("Debug").click()
            waitFor("Debug tab is selected", 30.seconds) { window.contentTabLabel("Debug").isSelected }
            closeToolWindow("MyToolWindow")
            waitFor("Wikisource tool window is hidden", 30.seconds) {
                withContext(OnDispatcher.EDT) { !getToolWindow("MyToolWindow").isVisible() }
            }
            openToolWindow("MyToolWindow")
            waitFor("Debug tab remains selected after reopening", 30.seconds) {
                window.contentTabLabel("Debug").isSelected
            }
            window.button { byVisibleText("Refresh") }.shouldBe(present)
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededBackendIsVisibleInDebugWindow(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-seeded-backend") {
            openToolWindow("MyToolWindow")
            val window = wikisourceWindow()
            window.contentTabLabel("Debug").click()
            window.button { byVisibleText("Refresh") }.click()
            window.x {
                and(byType("javax.swing.JLabel"), contains(byVisibleText("Status: ✓ connected")))
            }.shouldBe(present)
            waitFor("Seeded wiki is visible in backend diagnostics", 30.seconds) {
                window.getAllTexts().any { it.text.contains("/ide/en") }
            }
        }

    private fun Driver.wikisourceWindow(): UiComponent = ui.x {
        componentWithChild(byClass("InternalDecoratorImpl"), byAccessibleName("Debug"))
    }

    private fun withProject(
        projectDirectory: Path,
        testName: String,
        scenario: Driver.(String) -> Unit,
    ) {
        val fixtureText = requireNotNull(javaClass.getResource("/projects/wikitext/sample.wiki")).readText()

        projectDirectory.resolve("sample.wiki").writeText(fixtureText)

        val pluginArchive = Path.of(requireNotNull(System.getProperty("path.to.build.plugin")))

        val idePath = Path.of(requireNotNull(System.getProperty("wikitext.test.idePath")))

        val ideInfo = IdeInfo.IdeaUltimate.copy(getInstaller = { ExistingIdeInstaller(idePath) })

        val testContext =
            Starter.newContext(testName, TestCase(ideInfo, LocalProjectInfo(projectDirectory)))
                .apply {
                    PluginConfigurator(this).installPluginFromPath(pluginArchive)
                    // Keep the test deterministic: 2026.2.4's default Islands theme
                    // can refer to an unavailable editor scheme during project startup.
                    paths.configDir.resolve("options").createDirectories().resolve("laf.xml").writeText(
                        """
                    <application>
                      <component name="LafManager" autodetect="false">
                        <laf class-name="com.intellij.ide.ui.laf.darcula.DarculaLaf" />
                      </component>
                    </application>
                    """.trimIndent(),
                    )
                    applyVMOptionsPatch {
                        addSystemProperty("idea.trust.all.projects", true)
                        addSystemProperty("ide.show.tips.on.startup.default.value", false)
                        addSystemProperty("wtbot.baseUrl", wtbot.baseUrl ?: System.getProperty("wtbot.test.baseUrl"))
                    }
                }


        testContext.runIdeWithDriver()
            .useDriverAndCloseIde {
                try {
                    waitForIndicators(2.minutes)
                    scenario(fixtureText)
                } finally {
                    // Temporary observation pause; keep it off the IDE's EDT.
                    Thread.sleep(3.seconds.inWholeMilliseconds)
                }
            }
    }
}
