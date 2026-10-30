import org.gradle.api.tasks.bundling.AbstractArchiveTask

// End-to-end tests: IDE Starter downloads a real IDE (cached under
// build/ide-tests), installs the built plugin zip, launches it with the
// in-memory demo backend (-Dwtbot.fakeBackend=demo) and drives it through the
// Driver API. Deliberately NOT an IntelliJ-platform module: the tests run in a
// separate JVM from the IDE under test, so nothing here touches the platform
// classpath.
//
// `test` is disabled so `./gradlew check` (the pre-push hook) never launches an
// IDE; run `./gradlew :wikitext-ide-tests:uiTest` explicitly.

plugins {
    id("org.jetbrains.kotlin.jvm")
}

dependencies {
    testImplementation(libs.junit.jupiter)
    testImplementation(libs.kodein.di)
    testImplementation(libs.ide.starter.squashed)
    testImplementation(libs.ide.starter.junit5)
    testImplementation(libs.ide.starter.product.idea.ultimate) // IdeProductProvider.IU
    testImplementation(libs.ide.starter.driver)
    testImplementation(libs.driver.client)
    testImplementation(libs.driver.sdk)
    testImplementation(libs.driver.model)
}

val pluginZip = rootProject.tasks.named<AbstractArchiveTask>("buildPlugin")
    .flatMap { it.archiveFile }

tasks.test {
    enabled = false
}

val uiTest by tasks.registering(Test::class) {
    group = "verification"
    description = "Launches a real IDE with the built plugin and the demo backend, and drives it."

    val testSourceSet = sourceSets.test.get()
    testClassesDirs = testSourceSet.output.classesDirs
    classpath = testSourceSet.runtimeClasspath
    useJUnitPlatform()

    dependsOn(":buildPlugin")
    inputs.file(pluginZip).withPropertyName("pluginZip")

    // The IDE and its logs/screenshots land here, not in the sandbox used by runIde.
    val workDir = layout.buildDirectory.dir("ide-tests")
    systemProperty("ide.tests.work.dir", workDir.get().asFile.absolutePath)
    // Matches intellijPlatformVersion (gradle.properties); the IDE under test is
    // downloaded by Starter, not taken from the Gradle platform cache.
    systemProperty("ide.tests.build", providers.gradleProperty("ideTestBuild").orElse("262.8665.176").get())

    doFirst {
        systemProperty("path.to.build.plugin", pluginZip.get().asFile.absolutePath)
    }
    // Starter spawns a GUI IDE; show its output instead of swallowing it.
    testLogging {
        showStandardStreams = true
    }
}
