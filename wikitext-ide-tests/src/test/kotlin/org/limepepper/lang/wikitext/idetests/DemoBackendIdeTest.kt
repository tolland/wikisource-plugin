package org.limepepper.lang.wikitext.idetests

import com.intellij.driver.client.Driver
import com.intellij.driver.sdk.invokeAction
import com.intellij.driver.sdk.ui.components.common.ideFrame
import com.intellij.driver.sdk.waitForIndicators
import com.intellij.ide.starter.driver.engine.runIdeWithDriver
import com.intellij.ide.starter.ide.IdeProductProvider
import com.intellij.ide.starter.models.TestCase
import com.intellij.ide.starter.plugins.PluginConfigurator
import com.intellij.ide.starter.project.LocalProjectInfo
import com.intellij.ide.starter.runner.Starter
import org.junit.jupiter.api.Test
import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.writeText
import kotlin.time.Duration.Companion.minutes

/**
 * Smoke test: the plugin loads in a real IDE launched with the in-memory demo
 * backend, the project opens, and the tool window can be activated without the
 * IDE logging an error (Starter fails the test on those).
 *
 * Further tests should reuse [launch] and add their own `ideFrame { ... }` body.
 */
class DemoBackendIdeTest {

    @Test
    fun toolWindowActivatesAgainstDemoBackend() {
        launch("toolWindowActivatesAgainstDemoBackend") {
            ideFrame {
                waitForIndicators(2.minutes)
                invokeAction("ActivateMyToolWindowToolWindow", now = false)
            }
        }
    }

    private fun launch(testName: String, body: Driver.() -> Unit) {
        val projectDir = Files.createTempDirectory("wt-ide-test-project").also {
            it.resolve("sample.wt").writeText("== Sample ==\nHello '''world'''.\n")
        }
        val buildNumber = System.getProperty("ide.tests.build")
        val pluginZip = Path.of(requireNotNull(System.getProperty("path.to.build.plugin")) {
            "path.to.build.plugin is set by the uiTest Gradle task; run it via ./gradlew :wikitext-ide-tests:uiTest"
        })

        val context = Starter
            .newContext(
                testName,
                TestCase(IdeProductProvider.IU, LocalProjectInfo(projectDir)).withBuildNumber(buildNumber),
            )
            .apply {
                PluginConfigurator(this).installPluginFromPath(pluginZip)
                applyVMOptionsPatch {
                    addSystemProperty("wtbot.fakeBackend", "demo")
                }
            }

        context.runIdeWithDriver().useDriverAndCloseIde {
            body()
        }
    }
}
