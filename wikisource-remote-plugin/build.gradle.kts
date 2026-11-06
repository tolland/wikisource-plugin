import org.jetbrains.intellij.platform.gradle.TestFrameworkType
import org.jetbrains.intellij.platform.gradle.tasks.VerifyPluginTask

plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform")
}

val intellijPlatformVersion = providers.gradleProperty("intellijPlatformVersion").get()

dependencies {
    intellijPlatform {
        intellijIdea(intellijPlatformVersion) {
            useCache = true
        }
        pluginModule(implementation(project(":wikisource-remote-shared")))
        pluginModule(implementation(project(":wikisource-remote-backend")))
        pluginModule(implementation(project(":wikisource-remote-frontend")))
        bundledModule("intellij.platform.structureView")
        bundledModule("intellij.platform.ui.jcef")
        bundledModule("intellij.libraries.jcef")
    }
}

intellijPlatform {
    buildSearchableOptions = false
    pluginVerification {
        failureLevel = listOf()
    }
}

tasks.runIde { enabled = false }
