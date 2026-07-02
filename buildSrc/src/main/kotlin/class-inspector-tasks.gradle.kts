import org.gradle.api.tasks.SourceSetContainer
import org.gradle.jvm.toolchain.JavaToolchainService
import org.gradle.api.plugins.JavaPluginExtension

val sourceSets = extensions.getByType<SourceSetContainer>()
val javaToolchains = extensions.getByType<JavaToolchainService>()


val javaExtension = extensions.getByType<JavaPluginExtension>()

plugins {
    java
}

tasks.register<Exec>("javap") {
    group = "help"
    description = "Print the public JVM API of -Pclass=<fully.qualified.ClassName>"

    dependsOn("classes")

    val className = providers.gradleProperty("class")

    val launcher = javaToolchains.launcherFor {
        languageVersion.set(javaExtension.toolchain.languageVersion)
        vendor.set(javaExtension.toolchain.vendor)
        implementation.set(javaExtension.toolchain.implementation)
    }

    args(
        "-public",
        "-classpath",
        sourceSets.named("main").get().runtimeClasspath.asPath,
    )

    doFirst {
        require(className.isPresent) {
            "Usage: ./gradlew javap -Pclass=fully.qualified.ClassName"
        }

        executable(
            launcher.get()
                .metadata
                .installationPath
                .file("bin/javap")
                .asFile
                .absolutePath,
        )

        args(className.get())
    }
}
