import org.jetbrains.intellij.platform.gradle.TestFrameworkType

plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform.module")
    id("class-inspector-tasks")
    id("org.jetbrains.kotlin.plugin.serialization")
}

dependencies {
    compileOnly("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    testImplementation(libs.junit)
    testImplementation("org.jetbrains.kotlin:kotlin-test")
    testImplementation("org.jetbrains.kotlin:kotlin-test-junit")
    testImplementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
    intellijPlatform {
        testFramework(TestFrameworkType.Platform)
    }
}
