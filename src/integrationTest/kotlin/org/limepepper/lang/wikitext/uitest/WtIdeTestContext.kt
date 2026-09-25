package org.limepepper.lang.wikitext.uitest

import com.intellij.ide.starter.ci.CIServer
import com.intellij.ide.starter.ci.NoCIServer
import com.intellij.ide.starter.di.di
import com.intellij.ide.starter.ide.IDETestContext
import com.intellij.ide.starter.ide.installer.ExistingIdeInstaller
import com.intellij.ide.starter.models.IdeInfo
import com.intellij.ide.starter.models.TestCase
import com.intellij.ide.starter.plugins.PluginConfigurator
import com.intellij.ide.starter.project.LocalProjectInfo
import com.intellij.ide.starter.runner.Starter
import com.intellij.tools.ide.starter.product.idea.ultimate.IdeaUltimate
import org.junit.jupiter.api.fail
import org.kodein.di.DI
import org.kodein.di.bindSingleton
import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.copyToRecursively
import kotlin.io.path.createDirectories
import kotlin.io.path.deleteRecursively

/**
 * Builds Starter contexts for the plugin under test.
 *
 * Everything environment-specific comes in as system properties set by the
 * `integrationTest` Gradle task (see build.gradle.kts), so a test class only
 * says which project it wants open.
 */
object WtIdeTestContext {
    init {
        // Starter reports exceptions it finds in the IDE log through the CI
        // server; NoCIServer only prints them. Failing instead is what makes
        // "the plugin didn't throw" something these tests actually check.
        di = DI {
            extend(di)
            bindSingleton<CIServer>(overrides = true) {
                object : CIServer by NoCIServer {
                    override fun reportTestFailure(
                        testName: String,
                        message: String,
                        details: String,
                        linkToLogs: String?,
                    ) {
                        fail { "$testName: IDE reported an error: $message\n$details" }
                    }
                }
            }
        }
    }

    private fun property(name: String): String =
        requireNotNull(System.getProperty(name)) { "system property $name not set; run via ./gradlew integrationTest" }

    private val pluginZip: Path get() = Path.of(property("path.to.build.plugin"))
    private val platformPath: Path get() = Path.of(property("path.to.platform"))
    private val outputDir: Path get() = Path.of(property("uitest.output"))
    val wtbotBaseUrl: String get() = property("wtbot.baseUrl")

    /** The IDE Gradle resolved for the build, not a second download. */
    private val ide: IdeInfo
        get() = IdeInfo.IdeaUltimate.copy(getInstaller = { ExistingIdeInstaller(platformPath) })

    /**
     * A fresh copy of `test-projects/<name>` from the test resources, so the
     * IDE's `.idea` writes never land in the source tree and no run sees the
     * previous one's state.
     */
    @OptIn(kotlin.io.path.ExperimentalPathApi::class)
    private fun projectCopy(name: String): Path {
        val source = Path.of(
            requireNotNull(javaClass.classLoader.getResource("test-projects/$name")) {
                "no test project named $name"
            }.toURI(),
        )
        val target = outputDir.resolve("projects").resolve(name)
        if (Files.exists(target)) target.deleteRecursively()
        target.parent.createDirectories()
        source.copyToRecursively(target, followLinks = false, overwrite = true)
        return target
    }

    fun create(testName: String, projectName: String): IDETestContext =
        Starter.newContext(
            testName,
            TestCase(ide, LocalProjectInfo(projectCopy(projectName))),
        ).apply {
            PluginConfigurator(this).installPluginFromPath(pluginZip)
            applyVMOptionsPatch {
                withXmx(2048)
                addSystemProperty("idea.trust.all.projects", true)
                addSystemProperty("ide.show.tips.on.startup.default.value", false)
                addSystemProperty("jb.consents.confirmation.enabled", false)
                addSystemProperty("jb.privacy.policy.text", "<!--999.999-->")
                // WtbotAppSettings applies this at every startup, so the IDE
                // talks to the test backend regardless of persisted config.
                addSystemProperty("wtbot.baseUrl", wtbotBaseUrl)
            }
        }
}
