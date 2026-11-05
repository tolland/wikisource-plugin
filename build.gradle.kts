import org.jetbrains.intellij.platform.gradle.TestFrameworkType
import org.jetbrains.intellij.platform.gradle.tasks.PrepareSandboxTask
import org.jetbrains.intellij.platform.gradle.tasks.VerifyPluginTask
import org.jetbrains.kotlin.gradle.dsl.JvmDefaultMode
import org.jetbrains.kotlin.gradle.dsl.KotlinJvmProjectExtension

val sandboxPluginIds = listOf(
    "PsiViewer",
)

// Directory names created underneath <sandbox>/plugins.
// They are usually, but not necessarily, the same as the plugin ID.
val sandboxPluginDirectories = listOf(
    "PsiViewer",
)

val intellijPlatformVersion = providers.gradleProperty("intellijPlatformVersion").get()

// Which wtbot sidecar the sandbox IDE starts against, e.g.
//   ./gradlew runIde -PwtbotBaseUrl=http://127.0.0.1:18584
// Unset means "whatever the sandbox has persisted", which is the plugin's own
// default (http://127.0.0.1:18564, the workstation dev-convention port —
// see docs/reference/logging.md) on a fresh sandbox. The property is read at
// every launch, not just the first: the sandbox keeps its config between runs,
// so a first-run-only default would be ignored exactly when you're switching
// between the dev sidecar and the docker harness. It still only seeds the
// setting — the Settings page can move the IDE to another backend mid-session.
val wtbotBaseUrl = providers.gradleProperty("wtbotBaseUrl")
val wtbotTimeoutSeconds = providers.gradleProperty("wtbotTimeoutSeconds")

plugins {
    idea
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform")
    id("org.jetbrains.intellij.platform.module") apply false
    id("org.jetbrains.grammarkit") apply false
    id("org.jetbrains.kotlin.plugin.serialization") apply false
    id("com.diffplug.spotless")
}

// Real IDE tests stay separate from the fast platform/unit tests.
val integrationTestSourceSet = sourceSets.create("integrationTest")

idea {
    module {
    }
}

allprojects {
    plugins.withId("org.jetbrains.intellij.platform.module") {
        tasks.named<Test>("test") {
            // The 2026.2.4 Ultimate plugin registers a project startup activity
            // whose constructor cannot run in the light platform test fixture.
            // These tests exercise our plugin using the free platform APIs.
            systemProperty("idea.ignore.disabled.plugins", "false")
            systemProperty("idea.suppressed.plugins.id", "com.intellij.modules.ultimate")
        }
    }
    plugins.withId("org.jetbrains.kotlin.jvm") {
        extensions.configure<KotlinJvmProjectExtension> {
            compilerOptions {
                // Compile interface default methods without DefaultImpls bridges;
                // otherwise implementors of platform interfaces (ToolWindowFactory)
                // get compiler-generated overrides of deprecated members, which the
                // plugin verifier reports as deprecated-API usages.
                jvmDefault.set(JvmDefaultMode.NO_COMPATIBILITY)
            }
        }
    }
}


dependencies {
    intellijPlatform {
        intellijIdea(intellijPlatformVersion) {
            useCache = true
        }
        // @TODO put this back if new version comes out
        // plugin("psiviewer", version = "2026.1")
        plugin("org.jetbrains.plugins.kotlin.jupyter", version = "262.8665.176")
        plugin("com.intellij.notebooks.core", version = "262.8665.270")
        plugin("intellij.jupyter", version = "262.8665.339")
        plugin("nl.rubensten.texifyidea", version = "1.0.0")
        localPlugin(project(":wikitext-language-plugin"))
        localPlugin(project(":wikisource-remote-plugin"))
        testFramework(TestFrameworkType.Starter, configurationName = "integrationTestImplementation")
        testFramework(TestFrameworkType.Platform)
        bundledModule("intellij.platform.structureView")
        bundledModule("intellij.platform.ui.jcef")
        bundledModule("intellij.libraries.jcef")
    }
}

dependencies {
    // The standalone Starter process needs Kotlin even though IDE plugin modules
    // rely on the IDE-bundled runtime.
    "integrationTestImplementation"(kotlin("stdlib"))
    "integrationTestImplementation"(project(":wikitext-core"))
    "integrationTestImplementation"(project(":wikitext-language-ui"))
    "integrationTestImplementation"(project(":wikisource-remote-shared"))
    "integrationTestImplementation"(project(":wikisource-remote-backend"))
    "integrationTestImplementation"(project(":wikisource-remote-frontend"))
    "integrationTestImplementation"(kotlin("reflect"))
    "integrationTestImplementation"(platform("org.junit:junit-bom:5.12.2"))
    "integrationTestImplementation"("org.junit.jupiter:junit-jupiter")
    "integrationTestRuntimeOnly"("org.junit.platform:junit-platform-launcher")
    // Used by Starter's IDE-process reporter even outside TeamCity.
    "integrationTestRuntimeOnly"("org.jetbrains.teamcity:serviceMessages:2024.07")
    "integrationTestImplementation"("org.kodein.di:kodein-di-jvm:7.20.2")
    "integrationTestImplementation"("org.jetbrains.kotlinx:kotlinx-coroutines-core-jvm:1.10.1")
}

intellijPlatform {
    pluginVerification {
        // Experimental inlay hints and CustomWrap are accepted dependencies (see
        // ProofreadInlayProvider and PrpTextEditor). Report them for IDE upgrades,
        // while still failing on binary incompatibility, internal API usage, and
        // calls to override-only APIs. Deprecated usages require local justification.
        failureLevel = listOf(
            VerifyPluginTask.FailureLevel.COMPATIBILITY_PROBLEMS,
            VerifyPluginTask.FailureLevel.INTERNAL_API_USAGES,
            VerifyPluginTask.FailureLevel.OVERRIDE_ONLY_API_USAGES,
        )
    }

    // Disable buildSearchableOptions for development
    buildSearchableOptions = false

    caching {
        ides {
            enabled = true
            path = rootProject.layout.projectDirectory.dir(".intellijPlatform/ides")
        }
    }
}



tasks {

    // Apply workstation preferences only to development IDE launches. Other
    // sandboxes retain the platform plugin's isolated directories and suffixes.
    withType<PrepareSandboxTask>().matching {
        it.name in setOf("prepareSandbox", "prepareSandbox_runIdeWtbotLocal", "prepareSandbox_runIdeWtbotDocker")
    }.configureEach {
        sandboxDirectory =
            rootProject.layout.projectDirectory.dir(".intellijPlatform/custom-sandbox")
        sandboxSuffix = ""

        preserve {
            sandboxPluginDirectories.forEach {
                include("$it/**")
            }
        }

        // Declare sandbox config files as inputs for configuration cache compatibility
        inputs.files(
            "sandbox-config/ide.general.xml",
            "sandbox-config/ui.lnf.xml",
            "sandbox-config/trusted-paths.xml",
            "sandbox-config/editor.xml"
        )
            .withPropertyName("sandboxConfigFiles")

        doLast {
            // Use Gradle's built-in copy operations instead of Files.copy for configuration cache compatibility
            val optionsDir = sandboxConfigDirectory.file("options").get().asFile
            optionsDir.mkdirs()

            // Access files through the declared inputs
            val ideGeneralFile = inputs.files.find { it.name == "ide.general.xml" }
            val uiLnfFile = inputs.files.find { it.name == "ui.lnf.xml" }
            val trustedPaths = inputs.files.find { it.name == "trusted-paths.xml" }
            val editorFile = inputs.files.find { it.name == "editor.xml" }

            ideGeneralFile?.copyTo(
                optionsDir.resolve("ide.general.xml"),
                overwrite = true
            )

            uiLnfFile?.copyTo(
                optionsDir.resolve("ui.lnf.xml"),
                overwrite = true
            )

            trustedPaths?.copyTo(
                optionsDir.resolve("trusted-paths.xml"),
                overwrite = true
            )

            editorFile?.copyTo(
                optionsDir.resolve("editor.xml"),
                overwrite = true
            )
        }
    }

    runIde {
        jvmArgs = listOf(
            "-Djb.consents.confirmation.enabled=false",
            "-Djb.privacy.policy.text=\"<!--999.999-->\"",
            "-Didea.suppress.statistics.report=true",
            "-Didea.is.internal=true",
            "-Dide.ui.compact.mode=true",
            "-Dide.main.menu.separate=true",
            "-Didea.auto.reload.plugins=true",
            "-XX:+UnlockDiagnosticVMOptions",
            "-Dide.log.level=DEBUG",
        )

        args(listOf("nosplash"))

        argumentProviders += CommandLineArgumentProvider {
            listOf(rootProject.projectDir.parentFile.resolve("test-project").toString())
        }

        systemProperty("idea.auto.reload.plugins", "true")

        if (wtbotBaseUrl.isPresent) {
            systemProperty("wtbot.baseUrl", wtbotBaseUrl.get())
        }
        if (wtbotTimeoutSeconds.isPresent) {
            systemProperty("wtbot.timeoutSeconds", wtbotTimeoutSeconds.get())
        }
    }
}

intellijPlatformTesting {
    testIdeUi {
        listOf("integrationTest", "integrationTestExtended").forEach { taskName ->
            register(taskName) {
                sandboxDirectory = layout.buildDirectory.dir("$taskName-sandbox")
                task {
                    description = if (taskName == "integrationTest") {
                        "Runs the representative project/editor IDE smoke test."
                    } else {
                        "Runs the optional IDE tool-window interaction tests (supports --tests)."
                    }
                    testClassesDirs = integrationTestSourceSet.output.classesDirs
                    classpath = integrationTestSourceSet.runtimeClasspath
                    useJUnitPlatform {
                        includeEngines("junit-jupiter")
                        if (taskName == "integrationTest") {
                            excludeTags("extended")
                        } else {
                            includeTags("extended")
                        }
                    }
                    maxParallelForks = 1
                    if (taskName == "integrationTestExtended") {
                        // Both Starter suites replace the same cached IDE copy.
                        // Ordering applies only when both tasks are requested.
                        mustRunAfter("integrationTest")
                    }
                    dependsOn(":wikitext-language-plugin:buildPlugin", ":wikisource-remote-plugin:buildPlugin")
                    systemProperty("wikitext.test.idePath", platformPath.toString())
                    systemProperty("wikitext.test.pluginProfile", providers.gradleProperty("ideTestPluginProfile").getOrElse("platform"))
                    systemProperty("wikitext.test.pauseSeconds", providers.gradleProperty("ideTestPauseSeconds").getOrElse("0"))
                    systemProperty("wikitext.language.plugin.archive", project(":wikitext-language-plugin").layout.buildDirectory.file("distributions/wikitext-language-plugin-1.0.0-SNAPSHOT.zip").get().asFile.absolutePath)
                    systemProperty("wikisource.remote.plugin.archive", project(":wikisource-remote-plugin").layout.buildDirectory.file("distributions/wikisource-remote-plugin-1.0.0-SNAPSHOT.zip").get().asFile.absolutePath)
                    jvmArgs("--add-opens=java.base/sun.nio.fs=ALL-UNNAMED")
                    systemProperty("wtbot.test.baseUrl", "http://127.0.0.1:18594")
                }
            }
        }
    }

    runIde {
        register("runIdeWtbotLocal") {
            task {
                systemProperty(
                    "wtbot.baseUrl",
                    "http://127.0.100.1:18564",
                )
            }
        }

        register("runIdeWtbotDocker") {
            task {
                systemProperty(
                    "wtbot.baseUrl",
                    "http://localhost:18574",
                )
            }
        }
    }
}
