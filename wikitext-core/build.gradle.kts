import org.jetbrains.intellij.platform.gradle.TestFrameworkType

plugins {
    id("org.jetbrains.kotlin.jvm")
    id("org.jetbrains.intellij.platform")
    id("org.jetbrains.grammarkit")
}

val intellijPlatformVersion = providers.gradleProperty("intellijPlatformVersion").get()
val intellijPlatformLocalPath = providers.gradleProperty("intellijPlatformLocalPath")

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
        testFramework(TestFrameworkType.Platform)
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
