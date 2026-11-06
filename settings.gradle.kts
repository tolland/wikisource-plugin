import org.jetbrains.intellij.platform.gradle.extensions.intellijPlatform

rootProject.name = "wikisource"

pluginManagement {
    repositories {
        mavenCentral()
        gradlePluginPortal()
    }
    plugins {
        id("org.jetbrains.grammarkit") version "2023.3.0.3"
        id("org.jetbrains.intellij.platform") version "2.19.0"
        id("org.jetbrains.intellij.platform.module") version "2.19.0"
        id("org.jetbrains.kotlin.jvm") version "2.3.20"
        id("org.jetbrains.kotlin.plugin.serialization") version "2.3.20"
        id("com.diffplug.spotless") version ("8.7.0")
    }
}

plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
    // registers the intellijPlatform { defaultRepositories() } extension function
    id("org.jetbrains.intellij.platform.settings") version "2.18.0"
}

@Suppress("UnstableApiUsage")
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        mavenCentral()
        intellijPlatform {
            defaultRepositories()
        }
        maven("https://mvnrepository.com/artifact/com.jetbrains.intellij.tools/ide-starter-driver")
    }
}

include(":wikitext:wikitext-core")
include(":wikitext:wikitext-language-ui")
include(":wikitext:wikitext-language-plugin")
include(":wikisource:wikisource-remote-shared")
include(":wikisource:wikisource-remote-backend")
include(":wikisource:wikisource-remote-frontend")
include(":wikisource:wikisource-remote-plugin")
