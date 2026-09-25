import org.jetbrains.intellij.platform.gradle.TestFrameworkType
import org.jetbrains.intellij.platform.gradle.tasks.PrepareSandboxTask
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

// UI integration tests (`./gradlew integrationTest`) run against their own
// docker compose project on the test-port convention (AGENTS.md: 1858x), so
// they never touch the dev stack (1857x) or the workstation sidecar. Passing
// -PuiTestWtbotBaseUrl=... skips docker entirely and points the IDE at a
// backend you already have running; -PuiTestKeepBackend leaves the compose
// project up afterwards for poking at with the viewer or curl.
val uiTestComposeProject = providers.gradleProperty("uiTestComposeProject").orElse("wtbot-ui-test")
val uiTestWikiPort = providers.gradleProperty("uiTestWikiPort").orElse("18581")
val uiTestLocalWikiPort = providers.gradleProperty("uiTestLocalWikiPort").orElse("18582")
val uiTestViewerPort = providers.gradleProperty("uiTestViewerPort").orElse("18583")
val uiTestWtbotPort = providers.gradleProperty("uiTestWtbotPort").orElse("18584")
val uiTestExternalBackend = providers.gradleProperty("uiTestWtbotBaseUrl")
val uiTestWtbotBaseUrl = uiTestExternalBackend.orElse(uiTestWtbotPort.map { "http://127.0.0.1:$it" })
val uiTestKeepBackend = providers.gradleProperty("uiTestKeepBackend").isPresent
// Extra compose overlays on top of seeded + wtbot, e.g. -PuiTestComposeOverlays=compose.principles.yml
val uiTestComposeOverlays = providers.gradleProperty("uiTestComposeOverlays")
    .map { it.split(',').map(String::trim).filter(String::isNotEmpty) }
    .orElse(emptyList())

plugins {
    idea
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform")
    id("org.jetbrains.intellij.platform.module") apply false
    id("org.jetbrains.grammarkit") apply false
    id("org.jetbrains.kotlin.plugin.serialization") apply false
    id("com.diffplug.spotless")
}

idea {
    module {
    }
}

sourceSets {
    create("integrationTest") {
        compileClasspath += sourceSets.main.get().output
        runtimeClasspath += sourceSets.main.get().output
    }
}

configurations.named("integrationTestImplementation") {
    extendsFrom(configurations.testImplementation.get())
}

allprojects {
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
        pluginModule(implementation(project(":wikitext-core")))
        pluginModule(implementation(project(":wikitext-vfs")))
        pluginModule(implementation(project(":wikitext-ui")))
        testFramework(TestFrameworkType.Platform)
        testFramework(TestFrameworkType.Starter, configurationName = "integrationTestImplementation")
        bundledModule("intellij.platform.structureView")
        bundledModule("intellij.platform.ui.jcef")
        bundledModule("intellij.libraries.jcef")
    }
    "integrationTestImplementation"("org.junit.jupiter:junit-jupiter:5.13.4")
    "integrationTestRuntimeOnly"("org.junit.platform:junit-platform-launcher:1.13.4")
    "integrationTestImplementation"("org.kodein.di:kodein-di-jvm:7.26.1")
    "integrationTestImplementation"("org.jetbrains.kotlinx:kotlinx-coroutines-core-jvm:1.10.2")
}

intellijPlatform {
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

    withType<PrepareSandboxTask> {
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

        // The integrationTest backend, by hand: brings the compose project up
        // and opens a sandbox IDE on it, for writing XPath queries against
        // the Driver devtools or reproducing a failed UI test.
        register("runIdeUiTestBackend") {
            task {
                dependsOn("uiTestBackendUp")
                systemProperty("wtbot.baseUrl", uiTestWtbotBaseUrl.get())
            }
        }
    }
}

// -- UI integration tests ---------------------------------------------------
//
// The docker backend for them: the seeded wiki pair plus the wtbot API, in its
// own compose project so its volumes (and MW_SERVER, baked in at install time
// for one port) are never shared with the dev stack. `up --wait` blocks on the
// healthchecks, which only go green after seeding.
fun uiTestComposeCommand(vararg args: String): List<String> = buildList {
    addAll(listOf("docker", "compose", "-f", "compose.seeded.yml", "-f", "compose.wtbot.yml"))
    uiTestComposeOverlays.get().forEach { addAll(listOf("-f", it)) }
    addAll(listOf("--profile", "pair", "--profile", "api"))
    addAll(args)
}

fun Exec.uiTestComposeEnvironment() {
    workingDir = rootProject.projectDir
    environment("COMPOSE_PROJECT_NAME", uiTestComposeProject.get())
    environment("WIKISOURCE_PORT", uiTestWikiPort.get())
    environment("WIKISOURCE_LOCAL_PORT", uiTestLocalWikiPort.get())
    environment("WTBOT_PORT", uiTestWtbotPort.get())
    environment("WTBOT_VIEWER_PORT", uiTestViewerPort.get())
    // Every run starts from an empty sidecar database; the tests register
    // what they need. The wikis keep their (slow to build) volumes.
    environment("WTBOT_RESET_DB", "1")
}

val uiTestBackendUp = tasks.register<Exec>("uiTestBackendUp") {
    group = "verification"
    description = "Starts the docker compose backend (wiki pair + wtbot) for integrationTest."
    onlyIf("-PuiTestWtbotBaseUrl not set") { !uiTestExternalBackend.isPresent }
    uiTestComposeEnvironment()
    commandLine(uiTestComposeCommand("up", "-d", "--build", "--wait"))
}

val uiTestBackendDown = tasks.register<Exec>("uiTestBackendDown") {
    group = "verification"
    description = "Stops the integrationTest docker compose backend (volumes are kept)."
    onlyIf("-PuiTestWtbotBaseUrl not set") { !uiTestExternalBackend.isPresent }
    uiTestComposeEnvironment()
    commandLine(uiTestComposeCommand("down", "--remove-orphans"))
}

intellijPlatformTesting.testIdeUi.register("integrationTest") {
    task {
        group = "verification"
        description = "Launches the IDE with the plugin via Starter/Driver and drives its UI."
        val integrationTestSourceSet = sourceSets.getByName("integrationTest")
        testClassesDirs = integrationTestSourceSet.output.classesDirs
        classpath = integrationTestSourceSet.runtimeClasspath
        useJUnitPlatform()

        dependsOn(uiTestBackendUp)
        if (!uiTestKeepBackend) finalizedBy(uiTestBackendDown)

        val pluginZip = tasks.buildPlugin.flatMap { it.archiveFile }
        inputs.file(pluginZip).withPropertyName("pluginZip")
        systemProperty("path.to.build.plugin", pluginZip.get().asFile.absolutePath)
        // Reuse the IDE Gradle already resolved rather than letting Starter
        // download (and cache) a second copy of it.
        systemProperty("path.to.platform", intellijPlatform.platformPath.toString())
        systemProperty("wtbot.baseUrl", uiTestWtbotBaseUrl.get())
        systemProperty("uitest.wikiApiUrl", "http://127.0.0.1:${uiTestWikiPort.get()}/api.php")
        systemProperty("uitest.output", layout.buildDirectory.dir("ui-test").get().asFile.absolutePath)
        // UI runs are slow and stateful; never serve them from the build cache.
        outputs.upToDateWhen { false }
    }
}
