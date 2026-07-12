import org.jetbrains.intellij.platform.gradle.TestFrameworkType

plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform.module")
    id("class-inspector-tasks")
}

dependencies {
    implementation(project(":wikitext-core"))
    implementation(project(":wikitext-vfs"))

    testImplementation(libs.junit)
    testImplementation("org.jetbrains.kotlin:kotlin-test")
    testImplementation("org.jetbrains.kotlin:kotlin-test-junit")
    intellijPlatform {
        testFramework(TestFrameworkType.Platform)
        // this is required in 2026.2 but seems to break 2026.1
        // bundledModule("intellij.platform.ui.jcef")
    }
}
