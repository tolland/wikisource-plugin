import org.jetbrains.intellij.platform.gradle.TestFrameworkType

group = "org.limepepper.lang.wikitext"
version = "1.0"

val intellijPlatformVersion = providers.gradleProperty("intellijPlatformVersion").get()

plugins {
    // id("org.jetbrains.changelog")
    id("org.jetbrains.grammarkit") version "2023.3.0.3"
    id("org.jetbrains.intellij.platform")
    id("org.jetbrains.kotlin.jvm")
}

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }

}

dependencies {
    testImplementation(libs.junit)
    testImplementation("org.jetbrains.kotlin:kotlin-test")
    testImplementation("org.jetbrains.kotlin:kotlin-test-junit")
    intellijPlatform {
        intellijIdea(intellijPlatformVersion)
        testFramework(TestFrameworkType.Platform)
        // plugin("com.redhat.devtools.lsp4ij", version="0.20.1")
        plugin("psiviewer", version="2026.1")
    }
}

sourceSets {
    main {
        java {
            srcDirs("src/main/gen")
        }
    }
    test {
        java {
            srcDirs("src/main/gen")
        }
        kotlin {
            srcDirs("src/test/kotlin")
        }
    }
}

tasks {
    generateLexer {
        sourceFile.set(file("src/main/kotlin/org/limepepper/lang/wikitext/lexer/WikitextLexer.flex"))
        targetOutputDir.set(file("src/main/gen/org/limepepper/lang/wikitext/lexer"))
    }

    generateParser {
        sourceFile.set(file("src/main/kotlin/org/limepepper/lang/wikitext/parser/Wikitext.bnf"))
        targetRootOutputDir.set(file("src/main/gen"))
        pathToParser.set("org/limepepper/lang/wikitext/parser/WtParser.java")
        pathToPsiRoot.set("org/limepepper/lang/wikitext/psi")
        purgeOldFiles.set(true)
    }
}