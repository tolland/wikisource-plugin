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
        pluginModule(implementation(project(":wikitext-core")))
        pluginModule(implementation(project(":wikitext-language-ui")))
        bundledModule("intellij.platform.structureView")
    }
}

intellijPlatform {
    buildSearchableOptions = false
    pluginVerification {
        failureLevel = listOf(
            VerifyPluginTask.FailureLevel.COMPATIBILITY_PROBLEMS,
            VerifyPluginTask.FailureLevel.INTERNAL_API_USAGES,
            VerifyPluginTask.FailureLevel.OVERRIDE_ONLY_API_USAGES,
        )
    }
}
