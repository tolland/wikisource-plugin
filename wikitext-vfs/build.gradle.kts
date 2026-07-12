import org.jetbrains.intellij.platform.gradle.TestFrameworkType

plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform.module")
    id("class-inspector-tasks")
}

dependencies {
    implementation(project(":wikitext-core"))
    testImplementation(libs.junit)
    testImplementation("org.jetbrains.kotlin:kotlin-test")
    testImplementation("org.jetbrains.kotlin:kotlin-test-junit")
    intellijPlatform {
        testFramework(TestFrameworkType.Platform)
    }
}
