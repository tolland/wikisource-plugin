import org.gradle.kotlin.dsl.withType
import org.jetbrains.intellij.platform.gradle.TestFrameworkType
import org.jetbrains.intellij.platform.gradle.tasks.PrepareSandboxTask
import org.jetbrains.kotlin.gradle.dsl.JvmDefaultMode
import org.jetbrains.kotlin.gradle.dsl.KotlinJvmProjectExtension

val intellijPlatformVersion = providers.gradleProperty("intellijPlatformVersion").get()

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
        plugin("psiviewer", version = "2026.1")
        pluginModule(implementation(project(":wikitext-core")))
        pluginModule(implementation(project(":wikitext-vfs")))
        pluginModule(implementation(project(":wikitext-ui")))
        testFramework(TestFrameworkType.Platform)
    }
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
        sandboxDirectory = project.layout.buildDirectory.dir("custom-sandbox")
        sandboxSuffix = ""

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
    }
}
