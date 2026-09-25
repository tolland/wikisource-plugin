package org.limepepper.lang.wikitext.uitest

import com.intellij.driver.client.Remote
import com.intellij.driver.client.service
import com.intellij.driver.sdk.invokeAction
import com.intellij.driver.sdk.openFile
import com.intellij.driver.sdk.ui.components.common.codeEditor
import com.intellij.driver.sdk.ui.components.common.ideFrame
import com.intellij.driver.sdk.ui.components.elements.tree
import com.intellij.driver.sdk.ui.xQuery
import com.intellij.driver.sdk.waitForIndicators
import com.intellij.ide.starter.driver.engine.runIdeWithDriver
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assumptions.assumeTrue
import org.junit.jupiter.api.BeforeAll
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.TestInstance
import kotlin.time.Duration.Companion.minutes
import kotlin.time.Duration.Companion.seconds

/**
 * Boots the real IDE with the built plugin and drives it, at increasing
 * depth: the IDE comes up without errors, a local `.wt` file opens as
 * Wikitext, and the tool window reads the (docker) wtbot backend.
 *
 * Any exception the IDE logs fails the test (see [WtIdeTestContext]), so each
 * level is also a "the plugin didn't throw while doing this" check.
 */
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class WikisourceSmokeUiTest {
    private val backend = WtbotTestBackend.fromSystemProperties()

    private val site = TestSite(
        family = "uitest",
        code = "en",
        label = "uitest",
        apiUrl = System.getProperty("uitest.wikiApiUrl", "http://127.0.0.1:18581/api.php"),
    )

    @BeforeAll
    fun seedBackend() {
        assumeTrue(backend.isHealthy(), "wtbot not reachable at ${backend.baseUrl}")
        backend.ensureSite(site)
    }

    @Test
    fun `ide starts with the plugin and indexes the project`() {
        WtIdeTestContext.create("smoke/startup", PROJECT).runIdeWithDriver().useDriverAndCloseIde {
            waitForIndicators(5.minutes)
            val fileType = service<FileTypeManager>().getFileTypeByFileName("sample.wt")
            assertEquals("Wikitext", fileType.getName())
        }
    }

    @Test
    fun `wikitext file opens in an editor`() {
        WtIdeTestContext.create("smoke/editor", PROJECT).runIdeWithDriver().useDriverAndCloseIde {
            waitForIndicators(5.minutes)
            openFile("sample.wt")
            ideFrame {
                codeEditor().waitContainsText(text = "UI smoke heading", timeout = 30.seconds)
            }
        }
    }

    @Test
    fun `tool window lists sites from the wtbot backend`() {
        WtIdeTestContext.create("smoke/toolwindow", PROJECT).runIdeWithDriver().useDriverAndCloseIde {
            waitForIndicators(5.minutes)
            invokeAction("Activate${TOOL_WINDOW_ID}ToolWindow")
            ideFrame {
                tree(xQuery { byAccessibleName(VFS_TREE_NAME) })
                    .waitAnyTextsContains(text = site.vfsName, timeout = 30.seconds)
            }
        }
    }

    private companion object {
        const val PROJECT = "wikitext-smoke"

        /** `<toolWindow id=...>` in wikisource.wikitext-ui.xml. */
        const val TOOL_WINDOW_ID = "MyToolWindow"

        /** WikisourceBrowserToolWindowTab.TREE_ACCESSIBLE_NAME. */
        const val VFS_TREE_NAME = "Wikisource VFS"
    }
}

@Remote("com.intellij.openapi.fileTypes.FileTypeManager")
interface FileTypeManager {
    fun getFileTypeByFileName(fileName: String): FileType
}

@Remote("com.intellij.openapi.fileTypes.FileType")
interface FileType {
    fun getName(): String
}
