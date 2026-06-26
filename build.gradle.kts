import org.jetbrains.intellij.platform.gradle.IntelliJPlatformType
import org.jetbrains.intellij.platform.gradle.TestFrameworkType

val intellijPlatformVersion = providers.gradleProperty("intellijPlatformVersion").get()

plugins {
    id("org.jetbrains.kotlin.jvm") apply false
    id("org.jetbrains.intellij.platform")
    id("org.jetbrains.intellij.platform.module") apply false
    id("org.jetbrains.grammarkit") apply false
    id("org.jetbrains.kotlin.plugin.serialization") apply false
}
subprojects {
    apply(plugin = "org.jetbrains.intellij.platform.module")
    apply(plugin = "org.jetbrains.kotlin.jvm")
    apply(plugin = "org.jetbrains.kotlin.plugin.serialization")

    dependencies {
        intellijPlatform {
            intellijIdea(intellijPlatformVersion)
        }
    }
}

dependencies {
    intellijPlatform {
        intellijIdea(intellijPlatformVersion)
        plugin("psiviewer", version = "2026.1")
//        pluginModule(implementation(project(":wikitext-core")))
        testFramework(TestFrameworkType.Platform)
    }
}


tasks {
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
            listOf(rootProject.file("test-project").toString())
        }

        systemProperty("idea.auto.reload.plugins", "true")
    }
}
