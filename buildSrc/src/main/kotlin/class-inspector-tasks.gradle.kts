import org.gradle.api.tasks.SourceSetContainer
import org.gradle.jvm.toolchain.JavaToolchainService
import org.gradle.api.plugins.JavaPluginExtension

val sourceSets = extensions.getByType<SourceSetContainer>()
val javaToolchains = extensions.getByType<JavaToolchainService>()


val javaExtension = extensions.getByType<JavaPluginExtension>()

plugins {
    java
}

tasks.register<Exec>("javap_old") {
    group = "help"
    description = "Print the public JVM API of -Pclass=<fully.qualified.ClassName>"

    val className = providers.gradleProperty("class")

    val launcher = javaToolchains.launcherFor {
        languageVersion.set(javaExtension.toolchain.languageVersion)
        vendor.set(javaExtension.toolchain.vendor)
        implementation.set(javaExtension.toolchain.implementation)
    }

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

        args(
            "-public",
            "-classpath",
            sourceSets.main.get().compileClasspath.asPath,
            className.get(),
        )
    }
}

tasks.register("printCompileClasspath") {
    val compileClasspath =
        configurations.named("compileClasspath")

    doLast {
        compileClasspath.get().files
            .sortedBy { it.absolutePath }
            .forEach(::println)
    }
}

val javapLauncher = javaToolchains.launcherFor {
    languageVersion.set(javaExtension.toolchain.languageVersion)
    vendor.set(javaExtension.toolchain.vendor)
    implementation.set(javaExtension.toolchain.implementation)
}

tasks.register<JavapTask>("javap") {
    group = "help"
    description =
        "Print the public JVM API of -Pclass=<fully.qualified.ClassName>"

    className.set(providers.gradleProperty("class"))

    classpath.from(
        configurations.named("compileClasspath"),
    )

    launcher.set(javapLauncher)
}
