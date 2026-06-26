import org.jetbrains.intellij.platform.gradle.extensions.intellijPlatform

rootProject.name = "wikisource"

pluginManagement {
    repositories {
        mavenCentral()
        gradlePluginPortal()
        maven("https://packages.jetbrains.team/maven/p/ij/intellij-dependencies/")
    }
    plugins {
        id("org.jetbrains.grammarkit") version "2023.3.0.3"
        id("org.jetbrains.intellij.platform") version "2.16.0"
        id("org.jetbrains.intellij.platform.module") version "2.16.0"
        id("org.jetbrains.kotlin.jvm") version "2.3.20"
        id("org.jetbrains.kotlin.plugin.serialization") version "2.3.20"
    }
}

plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
    // registers the intellijPlatform { defaultRepositories() } extension function
    id("org.jetbrains.intellij.platform.settings") version "2.16.0"
}

@Suppress("UnstableApiUsage")
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        mavenCentral()
        intellijPlatform {
            defaultRepositories()
        }
    }
}

include("wikitext-core")
include("wikitext-ui")
