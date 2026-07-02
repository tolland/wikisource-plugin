plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform.module")
    id("class-inspector-tasks")
}

dependencies {
    implementation(project(":wikitext-core"))
    implementation(project(":wikitext-vfs"))
    implementation("org.xerial:sqlite-jdbc:3.53.2.0")
}
