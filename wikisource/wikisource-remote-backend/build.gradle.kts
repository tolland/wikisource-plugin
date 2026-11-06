import org.jetbrains.intellij.platform.gradle.TestFrameworkType

plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform.module")
    id("class-inspector-tasks")
}

dependencies {
    compileOnly(project(":wikitext:wikitext-core"))
    compileOnly(project(":wikisource:wikisource-remote-shared"))
    testImplementation(project(":wikitext:wikitext-core"))
    testImplementation(project(":wikisource:wikisource-remote-shared"))
    testImplementation(libs.junit)
    testImplementation("org.jetbrains.kotlin:kotlin-test")
    testImplementation("org.jetbrains.kotlin:kotlin-test-junit")
    intellijPlatform {
        testFramework(TestFrameworkType.Platform)
    }
}
