import org.gradle.api.DefaultTask
import org.gradle.api.GradleException
import org.gradle.api.file.ConfigurableFileCollection
import org.gradle.api.provider.Property
import org.gradle.api.tasks.Classpath
import org.gradle.api.tasks.Input
import org.gradle.api.tasks.Nested
import org.gradle.api.tasks.Optional
import org.gradle.api.tasks.TaskAction
import org.gradle.jvm.toolchain.JavaLauncher
import org.gradle.process.ExecOperations
import javax.inject.Inject

abstract class JavapTask @Inject constructor(
    private val execOperations: ExecOperations,
) : DefaultTask() {

    @get:Input
    @get:Optional
    abstract val className: Property<String>

    @get:Classpath
    abstract val classpath: ConfigurableFileCollection

    @get:Nested
    abstract val launcher: Property<JavaLauncher>

    @TaskAction
    fun runJavap() {
        val requestedClass = className.orNull
            ?: throw GradleException(
                "Usage: ./gradlew ${path} " +
                    "-Pclass=fully.qualified.ClassName",
            )

        execOperations.exec {
            executable(
                launcher.get()
                    .metadata
                    .installationPath
                    .file("bin/javap")
                    .asFile,
            )

            args(
                "-public",
                "-classpath",
                classpath.asPath,
                requestedClass,
            )
        }
    }
}
