import org.jetbrains.intellij.platform.gradle.TestFrameworkType
import org.gradle.api.tasks.JavaExec
import org.gradle.api.tasks.SourceSetContainer

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

val sourceSets = extensions.getByType<SourceSetContainer>()

tasks.register<JavaExec>("runAnnotationDemo") {
    group = "application"
    description = "Runs the standalone ImageAnnotationPane manual harness."

    dependsOn(tasks.named("testClasses"))

    mainClass.set("org.limepepper.lang.wikitext.annotation.AnnotationDemo")
    classpath = sourceSets.named("test").get().runtimeClasspath + configurations.named("intellijPlatformClasspath").get()
}
