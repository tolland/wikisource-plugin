plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform.module")
}

dependencies {
    implementation(project(":wikitext-core"))
    implementation("org.xerial:sqlite-jdbc:3.53.2.0")
}
