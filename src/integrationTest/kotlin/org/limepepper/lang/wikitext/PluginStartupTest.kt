package org.limepepper.lang.wikitext

import com.intellij.driver.client.Driver
import com.intellij.driver.client.Remote
import com.intellij.driver.client.service
import com.intellij.driver.client.utility
import com.intellij.driver.model.OnDispatcher
import com.intellij.driver.sdk.*
import com.intellij.driver.sdk.ui.components.UiComponent
import com.intellij.driver.sdk.ui.components.common.ideFrame
import com.intellij.driver.sdk.ui.components.common.popups.findInPathPopup
import com.intellij.driver.sdk.ui.components.elements.button
import com.intellij.driver.sdk.ui.components.elements.contentTabLabel
import com.intellij.driver.sdk.ui.components.elements.tree
import com.intellij.driver.sdk.ui.components.elements.popupMenu
import com.intellij.driver.sdk.ui.components.elements.actionButton
import com.intellij.driver.sdk.ui.components.elements.dialog
import com.intellij.driver.sdk.ui.components.elements.DialogUiComponent
import com.intellij.driver.sdk.ui.enabled
import com.intellij.driver.sdk.ui.present
import com.intellij.driver.sdk.ui.shouldBe
import com.intellij.driver.sdk.ui.ui
import com.intellij.ide.starter.ci.CIServer
import com.intellij.ide.starter.ci.NoCIServer
import com.intellij.ide.starter.di.di
import com.intellij.ide.starter.driver.engine.runIdeWithDriver
import com.intellij.ide.starter.models.IdeInfo
import com.intellij.ide.starter.models.TestCase
import com.intellij.ide.starter.plugins.PluginConfigurator
import com.intellij.ide.starter.project.LocalProjectInfo
import com.intellij.ide.starter.runner.Starter
import com.intellij.platform.testFramework.teamCity.TeamCityReporter.SyntheticTestKind
import com.intellij.tools.ide.starter.product.idea.ultimate.IdeaUltimate
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Tag
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.fail
import org.junit.jupiter.api.io.TempDir
import org.junit.jupiter.api.extension.RegisterExtension
import org.kodein.di.DI
import org.kodein.di.bindSingleton
import java.nio.file.Path
import org.limepepper.lang.wikitext.vfs.backend.HttpVfsBackend
import kotlin.io.path.createDirectories
import kotlin.io.path.writeText
import kotlin.io.path.readText
import kotlin.io.path.exists
import kotlin.time.Duration.Companion.minutes
import kotlin.time.Duration.Companion.seconds

/** Real IDE workflows; only @WithWtbot scenarios start a seeded local backend. */
class PluginStartupTest {
    companion object {
        private val ideInstaller by lazy {
            OncePerProcessIdeInstaller(Path.of(requireNotNull(System.getProperty("wikitext.test.idePath"))))
        }
    }

    @JvmField
    @RegisterExtension
    val wtbot = WtbotServerExtension()

    init {
        // Outside TeamCity, Starter otherwise only logs IDE-process failures.
        di = DI {
            extend(di)
            bindSingleton<CIServer>(overrides = true) {
                object : CIServer by NoCIServer {
                    override fun reportTestFailure(
                        testName: String,
                        message: String,
                        details: String,
                        linkToLogs: String?,
                        kind: SyntheticTestKind,
                        generifyTestName: Boolean,
                    ) {
                        fail("$testName: $message\n$details")
                    }
                }
            }
        }
    }

    @Test
    fun projectProvidesEditorAndToolWindows(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-project-editor") { fixtureText ->
            assertTrue(isPluginLoaded("org.limepepper.lang.wikitext"), "Wikitext plugin must be loaded")
            assertTrue(isPluginLoaded("org.limepepper.wikisource"), "Wikisource plugin must be loaded")

            openFile("sample.wiki")
            withContext(OnDispatcher.EDT) {
                val editor = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()) {
                    "The wikitext file must have a text editor"
                }
                assertEquals(fixtureText, editor.getDocument().getText())
                assertEquals("sample.wiki", editor.getVirtualFile().getName())
            }

            openToolWindow("Project")
            waitFor("Project tool window is visible", 30.seconds) {
                withContext(OnDispatcher.EDT) { getToolWindow("Project").isVisible() }
            }
            openToolWindow("Wikisource OCR")
            waitFor("Wikisource OCR tool window is visible", 30.seconds) {
                withContext(OnDispatcher.EDT) { getToolWindow("Wikisource OCR").isVisible() }
            }
        }

    @Test
    @Tag("extended")
    fun browserAndDebugTabsCanBeSwitched(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-tool-window-tabs") {
            openToolWindow("MyToolWindow")
            val window = wikisourceWindow()
            window.contentTabLabel("Debug").click()
            waitFor("Debug tab is selected", 30.seconds) { window.contentTabLabel("Debug").isSelected }
            window.button { byVisibleText("Refresh") }.shouldBe(present)
            window.contentTabLabel("Browser").click()
            waitFor("Browser tab is selected", 30.seconds) { window.contentTabLabel("Browser").isSelected }
            window.x { byType("javax.swing.JSplitPane") }.shouldBe(present)
        }

    @Test
    @Tag("extended")
    fun debugRefreshShowsBackendStatus(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-debug-refresh") {
            openToolWindow("MyToolWindow")
            val window = wikisourceWindow()
            window.contentTabLabel("Debug").click()
            window.button { byVisibleText("Refresh") }.click()
            // The sidecar is optional: both connected and offline are valid
            // results, but the endpoint and completed status must be visible.
            window.x {
                and(
                    byType("javax.swing.JLabel"),
                    contains(byVisibleText(requireNotNull(System.getProperty("wtbot.test.baseUrl")))),
                    or(contains(byVisibleText("Status: ✓")), contains(byVisibleText("Status: ✗"))),
                )
            }.shouldBe(present)
        }

    @Test
    @Tag("extended")
    fun reopeningToolWindowPreservesSelectedTab(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-tool-window-reopen") {
            openToolWindow("MyToolWindow")
            val window = wikisourceWindow()
            window.contentTabLabel("Debug").click()
            waitFor("Debug tab is selected", 30.seconds) { window.contentTabLabel("Debug").isSelected }
            closeToolWindow("MyToolWindow")
            waitFor("Wikisource tool window is hidden", 30.seconds) {
                withContext(OnDispatcher.EDT) { !getToolWindow("MyToolWindow").isVisible() }
            }
            openToolWindow("MyToolWindow")
            waitFor("Debug tab remains selected after reopening", 30.seconds) {
                window.contentTabLabel("Debug").isSelected
            }
            window.button { byVisibleText("Refresh") }.shouldBe(present)
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededBackendIsVisibleInDebugWindow(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-seeded-backend") {
            openToolWindow("MyToolWindow")
            val window = wikisourceWindow()
            window.contentTabLabel("Debug").click()
            window.button { byVisibleText("Refresh") }.click()
            window.x {
                and(byType("javax.swing.JLabel"), contains(byVisibleText("Status: ✓ connected")))
            }.shouldBe(present)
            waitFor("Seeded wiki is visible in backend diagnostics", 30.seconds) {
                window.getAllTexts().any { it.text.contains("/ide/en") }
            }
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededWorkAttachmentPersistsAndDetaches(@TempDir projectDirectory: Path) {
        val path = "/ide/en/Index/IDE integration.djvu/@wikitext"
        val backend = HttpVfsBackend(requireNotNull(wtbot.baseUrl))
        val original = backend.readContent(path).decodeText()
        val marker = " Detached editor remains editable."
        var phase = 0
        var managedId = 0
        withProject(projectDirectory, "wikitext-work-attachment", runs = 3,
            afterRun = { run, _ ->
                val settingsFile = projectDirectory.resolve(".idea/wikisource-works.xml")
                val saved = if (settingsFile.exists()) settingsFile.readText() else ""
                if (run == 0) {
                    assertTrue(saved.contains("wikisource-wtbot://$path"))
                    assertTrue(saved.contains("wikisource-wtbot:///ide/en/Page/IDE integration.djvu/2/@wikitext"))
                    assertTrue(saved.contains(requireNotNull(backend.stat(path).databaseId)))
                    assertTrue(!saved.contains("/@pages/") && !saved.contains("/@props"))
                } else assertTrue(!saved.contains("IDE integration.djvu"), "Detach must persist")
            }) {
            closeToolWindow("Project")
            openToolWindow("MyToolWindow")
            val tree = ui.tree("//div[@accessiblename='Wikisource Browser']")
            val work = arrayOf("Wikisource", "Attached works", "IDE integration.djvu")
            when (phase++) {
                0 -> {
                    tree.doubleClickPath("Wikisource", "ide/en", "Index", "IDE integration.djvu")
                    managedId = assertManagedEditor(path, original)
                    tree.clickPath("Wikisource", "ide/en", "Index", "IDE integration.djvu")
                    ui.button("Attach Work").click()
                    tree.expandPath("Wikisource", "Attached works")
                    waitFor("Work appears with bounded membership", 30.seconds) {
                        tree.collectExpandedPaths().any { it.path.last().contains("IDE integration.djvu (3 files)") }
                    }
                    tree.doubleClickPath(*(work + "Page IDE integration.djvu/2"), fullMatch = false)
                    assertManagedEditor("/ide/en/Page/IDE integration.djvu/2/@wikitext", "Integration page 2.")
                    tree.doubleClickPath(*(work + "Index text"), fullMatch = false)
                    assertEquals(managedId, assertManagedEditor(path, original))
                    // Reattaching through the ordinary browser updates the same association.
                    tree.clickPath("Wikisource", "ide/en", "Index", "IDE integration.djvu")
                    ui.button("Attach Work").click()
                    tree.expandPath("Wikisource", "Attached works")
                    waitFor("Reattach remains a single work", 30.seconds) {
                        tree.collectExpandedPaths().count { it.path.size == 3 && it.path[1] == "Attached works" } == 1
                    }
                }
                1 -> {
                    tree.doubleClickPath(*(work + "Index text"), fullMatch = false)
                    assertEquals(managedId, assertManagedEditor(path, original))
                    ui.xx("//div[@class='EditorComponentImpl']", UiComponent::class.java).list()
                        .single { it.component.isShowing() }.click()
                    invokeAction("EditorTextEnd")
                    ui.keyboard { typeText(marker) }
                    tree.clickPath(*work, fullMatch = false)
                    ui.button("Detach Work").click()
                    assertEquals(managedId, assertManagedEditor(path, original + marker))
                    withContext(OnDispatcher.EDT) {
                        val document = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()).getDocument()
                        assertTrue(service<ManagedTestDocumentManager>().isDocumentUnsaved(document))
                    }
                    assertEquals(original, backend.readContent(path).decodeText())
                    invokeAction("SaveAll")
                    waitFor("Detached editor can still save", 30.seconds) {
                        backend.readContent(path).decodeText() == original + marker
                    }
                }
                else -> {
                    tree.expandPath("Wikisource", "Attached works")
                    assertTrue(tree.collectExpandedPaths().none { it.path.size > 2 && it.path[1] == "Attached works" })
                    assertEquals(managedId, assertManagedEditor(path, original + marker))
                }
            }
        }
    }

    @Test
    @Tag("extended")
    @WithWtbot(scenario = "search")
    fun attachedWorkIndexSkipsUnreviewedDefaults(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-attached-work-index") {
            val backend = HttpVfsBackend(requireNotNull(wtbot.baseUrl))
            val prefix = "/ide/en/Page/IDE integration.djvu"
            val indexPath = "/ide/en/Index/IDE integration.djvu/@wikitext"
            val expected = setOf(indexPath, "$prefix/1/@wikitext", "$prefix/2/@wikitext", "$prefix/5/@wikitext")
            closeToolWindow("Project")
            openToolWindow("MyToolWindow")
            val tree = ui.tree("//div[@accessiblename='Wikisource Browser']")
            tree.clickPath("Wikisource", "ide/en", "Index", "IDE integration.djvu")
            ui.button("Attach Work").click()
            val attachedIndex = service<ManagedTestWorkIndex>(singleProject())
            waitFor("Contributor exposes real and locally saved text leaves", 30.seconds) {
                attachedIndex.files().map { it.getPath() }.toSet() == expected
            }
            val scope = attachedIndex.scopes().single()
            assertEquals("Wikisource: IDE integration.djvu", scope.getDisplayName())
            assertTrue(service<ManagedTestEditorManager>(singleProject()).getOpenFiles().isEmpty(), "Indexing must work on unopened files")
            val fileIndex = utility<ManagedTestFileBasedIndex>().getInstance()
            val idIndex = requireNotNull(utility<ManagedTestIndexId>().findByName("IdIndex"))
            fun wordFiles(word: String, searchScope: ManagedTestGlobalScope = scope): Set<String> = withReadAction {
                val key = new(ManagedTestWordIndexEntry::class, word, true)
                fileIndex.getContainingFiles(idIndex, key, searchScope).map { it.getPath() }.toSet()
            }
            waitFor("Native content index includes unopened remote transcriptions", 30.seconds) {
                wordFiles("Integration") == setOf("$prefix/1/@wikitext", "$prefix/2/@wikitext")
            }
            waitFor("Native content index includes a saved page without a remote revision", 30.seconds) {
                wordFiles("Saved") == setOf("$prefix/5/@wikitext")
            }
            assertTrue(wordFiles("Unreviewed").isEmpty())
            assertTrue(wordFiles("Unrelated").isEmpty())
            // Exercise the scope provider through the real Find in Files UI,
            // rather than relying only on direct FileBasedIndex queries.
            invokeAction("FindInPath")
            val findPopup = ui.ideFrame().findInPathPopup()
            findPopup.scopeActionButton.click()
            findPopup.scopeChooserComboBox.selectItem(scope.getDisplayName())
            findPopup.searchTextField.text = "Integration page"
            waitFor("Find in Files searches unopened work pages", 30.seconds) {
                findPopup.resultsTable.items.size == 2
            }
            findPopup.searchTextField.text = "Saved local transcription"
            waitFor("Find in Files searches locally created content", 30.seconds) {
                findPopup.resultsTable.items.size == 1
            }
            findPopup.searchTextField.text = "Unreviewed"
            waitFor("Find in Files excludes untouched defaults", 30.seconds) {
                findPopup.resultsTable.items.isEmpty()
            }
            findPopup.searchTextField.text = "Integration page 1."
            waitFor("Find result can be opened in the editor", 30.seconds) { findPopup.resultsTable.items.size == 1 }
            findPopup.resultsTable.doubleClickCell(0, 0)
            val searchedPath = "$prefix/1/@wikitext"
            val originalSearchText = backend.readContent(searchedPath).decodeText()
            val searchedId = assertManagedEditor(searchedPath, originalSearchText)
            // Navigation may retain a search wrapper (depending on the IDE
            // path/profile). Refresh must reload the existing editor either way;
            // unit regressions explicitly exercise CacheAvoidingVirtualFileWrapper.
            val refreshedSearchText = originalSearchText.replace("Integration page 1.", "Refreshed page 1.")
            wtbot.revise(searchedPath, refreshedSearchText, 404)
            ui.button("Refresh").click()
            assertEquals(searchedId, assertManagedEditor(searchedPath, refreshedSearchText))
            for (number in listOf(3, 4)) {
                val stat = backend.stat("$prefix/$number/@wikitext")
                assertTrue(stat.placeholder)
                assertTrue(!stat.dirty)
                assertNull(stat.revid)
            }

            // Explicitly review and save one default. It should join indexing
            // through the native save event, without detaching or reopening the project.
            val path = "$prefix/3/@wikitext"
            val original = backend.readContent(path).decodeText()
            openManagedUrl("wikisource-wtbot://$path")
            assertManagedEditor(path, original)
            ui.xx("//div[@class='EditorComponentImpl']", UiComponent::class.java).list()
                .single { it.component.isShowing() }.click()
            withContext(OnDispatcher.EDT) {
                val editor = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor())
                val position = original.indexOf("Unreviewed OCR default 3.") + "Unreviewed OCR default 3.".length
                editor.getCaretModel().moveToLogicalPosition(editor.offsetToLogicalPosition(position))
            }
            ui.keyboard { typeText(" Reviewed.") }
            invokeAction("SaveAll")
            waitFor("An explicitly saved default joins the contributor", 30.seconds) {
                attachedIndex.files().map { it.getPath() }.toSet() == expected + path
            }
            waitFor("The new transcription is indexed", 30.seconds) {
                wordFiles("Reviewed", attachedIndex.scopes().single()) == setOf(path)
            }
            assertTrue(backend.stat(path).dirty)
            assertTrue(backend.stat(path).placeholder)
            assertTrue(!backend.stat("$prefix/4/@wikitext").dirty)
            tree.clickPath("Wikisource", "Attached works", "IDE integration.djvu", fullMatch = false)
            ui.button("Detach Work").click()
            waitFor("Detach removes index roots and work scopes", 30.seconds) {
                attachedIndex.files().isEmpty() && attachedIndex.scopes().isEmpty()
            }
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededWorkMembershipRefreshAndRecovery(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-work-membership") {
            val backend = HttpVfsBackend(requireNotNull(wtbot.baseUrl))
            closeToolWindow("Project")
            openToolWindow("MyToolWindow")
            val tree = ui.tree("//div[@accessiblename='Wikisource Browser']")
            val status = cast(ui.x("//div[@accessiblename='Wikisource Work Status']").component, ManagedTestLabel::class)
            val work = arrayOf("Wikisource", "Attached works", "IDE integration.djvu")
            tree.clickPath("Wikisource", "ide/en", "Index", "IDE integration.djvu")
            ui.button("Attach Work").click()
            waitFor("Attach completes", 30.seconds) { status.getText().startsWith("Attached IDE integration.djvu: 3 files") }
            tree.expandPath(*work, fullMatch = false)
            assertEquals(3, tree.collectExpandedPaths().count { it.path.size == 4 && it.path[1] == "Attached works" })

            backend.deleteNode("/ide/en/Page/IDE integration.djvu/2")
            tree.clickPath(*work, fullMatch = false)
            ui.button("Refresh Work").click()
            waitFor("Removed member leaves attachment", 30.seconds) {
                status.getText().startsWith("Refreshed IDE integration.djvu: 2 files")
            }
            tree.expandPath(*work, fullMatch = false)
            assertEquals(2, tree.collectExpandedPaths().count { it.path.size == 4 && it.path[1] == "Attached works" })

            wtbot.stopServer()
            tree.clickPath(*work, fullMatch = false)
            ui.button("Refresh Work").click()
            waitFor("Outage retains confirmed membership", 30.seconds) { status.getText().startsWith("Work unavailable:") }
            tree.expandPath(*work, fullMatch = false)
            assertEquals(2, tree.collectExpandedPaths().count { it.path.size == 4 && it.path[1] == "Attached works" })

            wtbot.restartServer()
            tree.clickPath(*work, fullMatch = false)
            ui.button("Refresh Work").click()
            waitFor("Same database recovers", 30.seconds) { status.getText().startsWith("Refreshed IDE integration.djvu: 2 files") }

            wtbot.replaceDatabase(8)
            tree.clickPath(*work, fullMatch = false)
            ui.button("Refresh Work").click()
            waitFor("Replacement database requires explicit reattachment", 30.seconds) {
                status.getText().contains("Work belongs to a different database")
            }
            tree.expandPath(*work, fullMatch = false)
            assertEquals(2, tree.collectExpandedPaths().count { it.path.size == 4 && it.path[1] == "Attached works" })
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededManagedFilesHavePersistentIds(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-managed-file-identity") {
            val manager = service<ManagedTestVirtualFileManager>()
            val managingFs = utility<ManagedTestManagingFs>().getInstance()
            val paths = listOf(
                "/ide/en/Index/IDE integration.djvu/@wikitext",
                "/ide/en/Page/IDE integration.djvu/1/@wikitext",
                "/ide/en/Page/IDE integration.djvu/1/@props",
            )
            val ids = paths.map { path ->
                val url = "wikisource-wtbot://$path"
                val file = requireNotNull(manager.findFileByUrl(url)) { "Cannot resolve $url" }
                val id = cast(file, ManagedTestFileId::class).getId()
                assertTrue(id > 0, "Managed IDs must be platform-assigned positive integers")
                assertEquals(url, requireNotNull(managingFs.findFileById(id)).getUrl())
                assertTrue(file.isValid())
                assertEquals(path, file.getPath())
                assertTrue(file.getLength() > 0)
                assertEquals(!path.endsWith("/@props"), file.isWritable())
                assertEquals(id, cast(requireNotNull(manager.findFileByUrl(url)), ManagedTestFileId::class).getId())
                id
            }
            assertEquals(ids.size, ids.toSet().size, "Different titles/aspects need different managed IDs")
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededBrowserOpensManagedFilesAndNavigatesPages(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-managed-browser-navigation") {
            closeToolWindow("Project")
            openToolWindow("MyToolWindow")
            // Browser is the initial content. Address its accessible tree directly:
            // narrow tool-window headers may fold the content tabs into a menu.
            val tree = ui.tree("//div[@accessiblename='Wikisource Browser']")
            val index = arrayOf("Wikisource", "ide/en", "Index", "IDE integration.djvu")
            val page = index + arrayOf("Pages", "1")

            tree.doubleClickPath(*index)
            assertManagedEditor("/ide/en/Index/IDE integration.djvu/@wikitext", "<pagelist")
            withContext(OnDispatcher.EDT) {
                val file = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()).getVirtualFile()
                assertEquals("Proofread Index Editor", requireNotNull(service<ManagedTestEditorManager>(singleProject())
                    .getSelectedEditor(file)).getName())
            }

            tree.rightClickPath(*index)
            ui.popupMenu().select("Show Properties")
            val propsPath = "/ide/en/Index/IDE integration.djvu/@props"
            assertManagedEditor(propsPath, "{")
            assertTrue(!requireNotNull(service<ManagedTestVirtualFileManager>()
                .findFileByUrl("wikisource-wtbot://$propsPath")).isWritable())

            tree.doubleClickPath(*page, fullMatch = false)
            val firstPath = "/ide/en/Page/IDE integration.djvu/1/@wikitext"
            val firstId = assertManagedEditor(firstPath, "Integration page 1.")
            ui.actionButton { byAccessibleName("Next Page") }.shouldBe(enabled).click()
            assertManagedEditor("/ide/en/Page/IDE integration.djvu/2/@wikitext", "Integration page 2.")
            ui.actionButton { byAccessibleName("Previous Page") }.shouldBe(enabled).click()
            assertEquals(firstId, assertManagedEditor(firstPath, "Integration page 1."))

            // The browser must reuse the managed tab opened by toolbar navigation.
            tree.rightClickPath(*page, fullMatch = false)
            ui.popupMenu().select("Open")
            assertEquals(firstId, assertManagedEditor(firstPath, "Integration page 1."))
            withContext(OnDispatcher.EDT) {
                val files = service<ManagedTestEditorManager>(singleProject()).getOpenFiles()
                assertEquals(1, files.count { it.getPath() == firstPath })
                files.forEach { file ->
                    assertTrue(cast(file, ManagedTestVirtualFile::class).getUrl().startsWith("wikisource-wtbot://"))
                }
            }

            tree.rightClickPath(*page, fullMatch = false)
            ui.popupMenu().select("Mark Ready to Validate")
            ui.button("OK").click()
            assertManagedEditor(firstPath, "level=\"3\"")
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededManagedEditorSavesAndReopens(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-managed-editor-save") {
            val path = "/ide/en/Index/IDE integration.djvu/@wikitext"
            // A separate HTTP client observes wtbot independently of IDE caches.
            val backend = HttpVfsBackend(requireNotNull(wtbot.baseUrl))
            val original = backend.readContent(path).decodeText()
            val marker = " Managed editor save probe."
            closeToolWindow("Project")
            openToolWindow("MyToolWindow")
            val tree = ui.tree("//div[@accessiblename='Wikisource Browser']")
            val index = arrayOf("Wikisource", "ide/en", "Index", "IDE integration.djvu")
            tree.doubleClickPath(*index)
            val id = assertManagedEditor(path, original)

            invokeAction("EditorTextEnd")
            ui.keyboard { typeText(marker) }
            assertManagedEditor(path, original + marker)
            invokeAction("SaveAll")
            waitFor("Managed editor save reaches wtbot", 30.seconds) {
                backend.readContent(path).decodeText() == original + marker
            }
            assertTrue(backend.stat(path).dirty, "Saving must create a local journal edit")

            withContext(OnDispatcher.EDT) {
                val file = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()).getVirtualFile()
                service<FileEditorManager>(singleProject()).closeFile(file)
            }
            tree.doubleClickPath(*index)
            assertEquals(id, assertManagedEditor(path, original + marker))

            // The proofread editor has guarded header/footer markup: type in its body.
            val pagePath = "/ide/en/Page/IDE integration.djvu/1/@wikitext"
            val originalPage = backend.readContent(pagePath).decodeText()
            val expectedPage = originalPage.replace("Integration page 1.", "Integration page 1.$marker")
            val page = index + arrayOf("Pages", "1")
            tree.doubleClickPath(*page, fullMatch = false)
            val pageId = assertManagedEditor(pagePath, originalPage)
            withContext(OnDispatcher.EDT) {
                val editor = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor())
                val bodyEnd = originalPage.indexOf("Integration page 1.") + "Integration page 1.".length
                // Markup has visual soft wraps; position using the actual document offset.
                editor.getCaretModel().moveToLogicalPosition(editor.offsetToLogicalPosition(bodyEnd))
            }
            ui.keyboard { typeText(marker) }
            assertManagedEditor(pagePath, expectedPage)
            invokeAction("SaveAll")
            waitFor("Proofread editor save reaches wtbot", 30.seconds) {
                backend.readContent(pagePath).decodeText() == expectedPage
            }
            assertTrue(backend.stat(pagePath).dirty)
            withContext(OnDispatcher.EDT) {
                val file = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()).getVirtualFile()
                service<FileEditorManager>(singleProject()).closeFile(file)
            }
            tree.doubleClickPath(*page, fullMatch = false)
            assertEquals(pageId, assertManagedEditor(pagePath, expectedPage))
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededManagedRefreshesExternalContent(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-managed-external-refresh") {
            val path = "/ide/en/Index/IDE integration.djvu/@wikitext"
            val backend = HttpVfsBackend(requireNotNull(wtbot.baseUrl))
            val original = backend.readContent(path).decodeText()
            closeToolWindow("Project")
            openToolWindow("MyToolWindow")
            ui.tree("//div[@accessiblename='Wikisource Browser']").doubleClickPath(
                "Wikisource", "ide/en", "Index", "IDE integration.djvu")
            val id = assertManagedEditor(path, original)
            val revised = original.replace("to=\"2\"", "to=\"3\"")
            assertEquals(original.length, revised.length)
            assertTrue(original != revised)
            wtbot.revise(path, revised, 202)
            ui.button("Refresh").click()
            assertEquals(id, assertManagedEditor(path, revised))
            assertEquals(revised, backend.readContent(path).decodeText())
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededManagedSurvivesIdeRestart(@TempDir projectDirectory: Path) {
        val path = "/ide/en/Index/IDE integration.djvu/@wikitext"
        val backend = HttpVfsBackend(requireNotNull(wtbot.baseUrl))
        val original = backend.readContent(path).decodeText()
        val revised = original.replace("to=\"2\"", "to=\"4\"")
        var phase = 0
        var firstId = 0
        withProject(projectDirectory, "wikitext-managed-restart", runs = 2,
            afterRun = { run, _ -> if (run == 0) wtbot.revise(path, revised, 303) }) {
            if (phase++ == 0) {
                closeToolWindow("Project")
                openToolWindow("MyToolWindow")
                ui.tree("//div[@accessiblename='Wikisource Browser']").doubleClickPath(
                    "Wikisource", "ide/en", "Index", "IDE integration.djvu")
                firstId = assertManagedEditor(path, original)
                invokeAction("SaveAll")
            } else {
                assertEquals(firstId, assertManagedEditor(path, revised))
                assertEquals(revised, backend.readContent(path).decodeText())
                withContext(OnDispatcher.EDT) {
                    val file = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()).getVirtualFile()
                    assertEquals("Proofread Index Editor", requireNotNull(service<ManagedTestEditorManager>(singleProject())
                        .getSelectedEditor(file)).getName())
                }
            }
        }
    }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededManagedConflictPreservesUnsavedText(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-managed-conflict") {
            val path = "/ide/en/Index/IDE integration.djvu/@wikitext"
            val backend = HttpVfsBackend(requireNotNull(wtbot.baseUrl))
            val original = backend.readContent(path).decodeText()
            closeToolWindow("Project")
            openToolWindow("MyToolWindow")
            ui.tree("//div[@accessiblename='Wikisource Browser']").doubleClickPath(
                "Wikisource", "ide/en", "Index", "IDE integration.djvu")
            assertManagedEditor(path, original)
            invokeAction("EditorTextEnd")
            ui.keyboard { typeText(" Unsaved local edit.") }
            val local = original + " Unsaved local edit."
            assertManagedEditor(path, local)
            val remote = original.replace("to=\"2\"", "to=\"8\"")
            wtbot.revise(path, remote, 808)
            ui.button("Refresh").click()
            ui.dialog(title = "File Cache Conflict").button("Keep Memory Changes").click()
            assertManagedEditor(path, local)
            invokeAction("SaveAll")
            closeSaveFailures("Edit conflict")
            assertManagedEditor(path, local)
            assertEquals(remote, backend.readContent(path).decodeText(), "Stale save must not overwrite remote content")
            waitFor("Failed save keeps the Document unsaved", 10.seconds) {
                withContext(OnDispatcher.EDT) {
                    val document = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()).getDocument()
                    utility<ManagedTestDocumentManager>().getInstance().isDocumentUnsaved(document)
                }
            }
            withContext(OnDispatcher.EDT) {
                val document = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()).getDocument()
                val manager = utility<ManagedTestDocumentManager>().getInstance()
                assertTrue(manager.isDocumentUnsaved(document))
                // Explicitly discard only this scenario's controlled local edit before shutdown.
                manager.reloadFromDisk(document)
            }
            assertManagedEditor(path, remote)
            ui.xx("//div[@class='EditorComponentImpl']", UiComponent::class.java).list()
                .single { it.component.isShowing() }.click()
            invokeAction("EditorTextEnd")
            ui.keyboard { typeText(" Resolved edit.") }
            invokeAction("SaveAll")
            waitFor("Saving works after explicit reload", 30.seconds) {
                backend.readContent(path).decodeText() == remote + " Resolved edit."
            }
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededManagedRecoversFromBackendOutage(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-managed-outage") {
            val path = "/ide/en/Index/IDE integration.djvu/@wikitext"
            val pagePath = "/ide/en/Page/IDE integration.djvu/1/@wikitext"
            val backend = HttpVfsBackend(requireNotNull(wtbot.baseUrl))
            val original = backend.readContent(path).decodeText()
            val pageOriginal = backend.readContent(pagePath).decodeText()
            closeToolWindow("Project")
            openToolWindow("MyToolWindow")
            openManagedUrl("wikisource-wtbot://$pagePath")
            val pageId = assertManagedEditor(pagePath, pageOriginal)
            openManagedUrl("wikisource-wtbot://$path")
            val id = assertManagedEditor(path, original)
            ui.xx("//div[@class='EditorComponentImpl']", UiComponent::class.java).list()
                .single { it.component.isShowing() }.click()
            invokeAction("EditorTextEnd")
            ui.keyboard { typeText(" Retained through outage.") }
            val local = original + " Retained through outage."
            assertManagedEditor(path, local)
            wtbot.stopServer()
            try {
                assertTrue(runCatching { backend.stat(path) }.isFailure, "The owned HTTP server must really be unavailable")
                ui.button("Refresh").click()
                invokeAction("SaveAll")
                closeSaveFailures("failed")
                assertEquals(id, assertManagedEditor(path, local))
                waitFor("Outage save keeps the Document unsaved", 10.seconds) {
                    withContext(OnDispatcher.EDT) {
                        val document = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()).getDocument()
                        utility<ManagedTestDocumentManager>().getInstance().isDocumentUnsaved(document)
                    }
                }
            } finally {
                // Even an assertion failure must leave shutdown able to save this test's edits.
                wtbot.restartServer()
            }
            assertEquals(original, backend.readContent(path).decodeText(), "The rejected save must not reach the database")
            invokeAction("SaveAll")
            waitFor("Retry after service restart reaches the original database", 30.seconds) {
                backend.readContent(path).decodeText() == local
            }
            assertTrue(backend.stat(path).dirty)
            val revisedPage = pageOriginal.replace("page 1.", "page 9.")
            wtbot.revise(pagePath, revisedPage, 950)
            ui.button("Refresh").click()
            openManagedUrl("wikisource-wtbot://$pagePath")
            assertEquals(pageId, assertManagedEditor(pagePath, revisedPage))
            openManagedUrl("wikisource-wtbot://$path")
            assertEquals(id, assertManagedEditor(path, local))
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededManagedRejectsReplacementDatabase(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-database-replacement") {
            val path = "/ide/en/Index/IDE integration.djvu/@wikitext"
            val backend = HttpVfsBackend(requireNotNull(wtbot.baseUrl))
            val original = backend.readContent(path)
            val before = backend.stat(path)
            closeToolWindow("Project")
            openToolWindow("MyToolWindow")
            openManagedUrl("wikisource-wtbot://$path")
            val id = assertManagedEditor(path, original.decodeText())
            wtbot.replaceDatabase(7)
            val replacement = backend.readContent(path)
            val after = backend.stat(path)
            assertTrue(original.databaseId != replacement.databaseId)
            assertEquals(before.revid, after.revid)
            assertEquals(before.timestamp, after.timestamp)
            assertEquals(before.length, after.length)
            openManagedUrl("wikisource-wtbot://$path")
            assertEquals(id, assertManagedEditor(path, replacement.decodeText()))
            ui.button("Refresh").click()
            ui.xx("//div[@class='EditorComponentImpl']", UiComponent::class.java).list()
                .single { it.component.isShowing() }.click()
            invokeAction("EditorTextEnd")
            ui.keyboard { typeText(" Unsaved replacement edit.") }
            val local = replacement.decodeText() + " Unsaved replacement edit."
            assertManagedEditor(path, local)
            wtbot.replaceDatabase(8)
            val latest = backend.readContent(path)
            assertTrue(latest.databaseId != replacement.databaseId)
            assertEquals(replacement.revid, latest.revid)
            invokeAction("SaveAll")
            closeSaveFailures("Database changed")
            assertEquals(latest.decodeText(), backend.readContent(path).decodeText())
            assertManagedEditor(path, local)
            waitFor("Database rejection preserves unsaved text", 10.seconds) {
                withContext(OnDispatcher.EDT) {
                    val doc = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()).getDocument()
                    utility<ManagedTestDocumentManager>().getInstance().isDocumentUnsaved(doc)
                }
            }
            withContext(OnDispatcher.EDT) {
                utility<ManagedTestDocumentManager>().getInstance().reloadFromDisk(
                    requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()).getDocument())
            }
            assertEquals(id, assertManagedEditor(path, latest.decodeText()))
            ui.xx("//div[@class='EditorComponentImpl']", UiComponent::class.java).list()
                .single { it.component.isShowing() }.click()
            invokeAction("EditorTextEnd")
            ui.keyboard { typeText(" Accepted in new database.") }
            invokeAction("SaveAll")
            waitFor("Save binds to the newly loaded database", 30.seconds) {
                backend.readContent(path).decodeText() == latest.decodeText() + " Accepted in new database."
            }
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededManagedRecoversFromRequestTimeout(@TempDir projectDirectory: Path) =
        withProject(projectDirectory, "wikitext-request-timeout", requestTimeoutSeconds = 1) {
            val path = "/ide/en/Index/IDE integration.djvu/@wikitext"
            val backend = HttpVfsBackend(requireNotNull(wtbot.baseUrl))
            val original = backend.readContent(path).decodeText()
            closeToolWindow("Project")
            openToolWindow("MyToolWindow")
            openManagedUrl("wikisource-wtbot://$path")
            val id = assertManagedEditor(path, original)
            try {
                wtbot.stall("GET", "/vfs/stat", 4)
                ui.button("Refresh").click()
                assertManagedEditor(path, original)
                wtbot.stall()
                ui.xx("//div[@class='EditorComponentImpl']", UiComponent::class.java).list()
                    .single { it.component.isShowing() }.click()
                invokeAction("EditorTextEnd")
                ui.keyboard { typeText(" Retained through timeout.") }
                wtbot.stall("POST", "/vfs/content", 4)
                invokeAction("SaveAll")
                closeSaveFailures("timed out")
                assertEquals(id, assertManagedEditor(path, original + " Retained through timeout."))
                waitFor("Timed-out save remains unsaved", 10.seconds) {
                    withContext(OnDispatcher.EDT) {
                        val doc = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()).getDocument()
                        utility<ManagedTestDocumentManager>().getInstance().isDocumentUnsaved(doc)
                    }
                }
            } finally { wtbot.stall() }
            assertEquals(original, backend.readContent(path).decodeText())
            invokeAction("SaveAll")
            waitFor("Retry succeeds after the timeout fault is cleared", 30.seconds) {
                backend.readContent(path).decodeText() == original + " Retained through timeout."
            }
        }

    @Test
    @Tag("extended")
    @WithWtbot
    fun seededManagedFilesRestoreOffline(@TempDir projectDirectory: Path) {
        val path = "/ide/en/Index/IDE integration.djvu/@wikitext"
        val propsPath = "/ide/en/Index/IDE integration.djvu/@props"
        val backend = HttpVfsBackend(requireNotNull(wtbot.baseUrl))
        val original = backend.readContent(path).decodeText()
        val marker = " Restored managed file."
        var phase = 0
        var id = 0
        withProject(projectDirectory, "wikitext-managed-offline-restore", runs = 2,
            restoredFiles = listOf("wikisource-wtbot://$propsPath", "wikisource-wtbot://$path"),
            afterRun = { run, workspace ->
                val xml = java.nio.file.Files.readString(workspace)
                assertTrue(xml.contains("file=\"wikisource-wtbot://$path\""))
                if (run == 0) wtbot.stopServer()
            }) {
            val manager = service<ManagedTestVirtualFileManager>()
            assertNull(manager.getFileSystem("wikisource"), "The old protocol must not be registered")
            assertNull(manager.getFileSystem("wikisource-demo"), "The demo protocol must not be registered")
            assertEquals("wikisource-wtbot", requireNotNull(manager.getFileSystem("wikisource-wtbot")).getProtocol())
            try {
                if (phase == 1) assertTrue(runCatching { backend.stat(path) }.isFailure)
                waitFor("Managed editor tabs restore", 30.seconds) {
                    withContext(OnDispatcher.EDT) {
                        service<ManagedTestEditorManager>(singleProject()).getOpenFiles().map { it.getUrl() }.sorted() ==
                            listOf("wikisource-wtbot://$path", "wikisource-wtbot://$propsPath").sorted()
                    }
                }
                if (phase == 1) {
                    assertEquals(id, assertManagedEditor(path, original + marker))
                    withContext(OnDispatcher.EDT) {
                        val file = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor()).getVirtualFile()
                        assertEquals("Proofread Index Editor", requireNotNull(service<ManagedTestEditorManager>(singleProject())
                            .getSelectedEditor(file)).getName())
                    }
                }
            } finally {
                if (phase == 1) wtbot.restartServer()
            }
            val props = requireNotNull(manager.findFileByUrl("wikisource-wtbot://$propsPath"))
            assertTrue(!props.isWritable())
            openManagedUrl("wikisource-wtbot://$path")
            if (phase++ == 0) {
                id = assertManagedEditor(path, original)
                openManagedUrl("wikisource-wtbot://$path")
                assertEquals(id, assertManagedEditor(path, original))
                ui.xx("//div[@class='EditorComponentImpl']", UiComponent::class.java).list()
                    .single { it.component.isShowing() }.click()
                invokeAction("EditorTextEnd")
                ui.keyboard { typeText(marker) }
                invokeAction("SaveAll")
                waitFor("Restored editor saves through managed VFS", 30.seconds) {
                    backend.readContent(path).decodeText() == original + marker
                }
            } else {
                assertEquals(id, assertManagedEditor(path, original + marker))
            }
            assertEquals(2, service<ManagedTestEditorManager>(singleProject()).getOpenFiles().size)
        }
    }

    private fun Driver.openManagedUrl(url: String) {
        val file = requireNotNull(service<ManagedTestVirtualFileManager>().findFileByUrl(url))
        assertTrue(cast(file, ManagedTestFileId::class).getId() > 0)
        withContext(OnDispatcher.EDT) {
            service<ManagedTestEditorManager>(singleProject()).openFile(file, true)
        }
    }

    private fun Driver.closeSaveFailures(expected: String) {
        val failures = ui.xx("//div[@title='Cannot Save Files']", DialogUiComponent::class.java)
        var failuresSeen = 0
        var lastFailure = System.nanoTime()
        waitFor("Save errors are shown and closed: $expected", 20.seconds) {
            val visible = failures.list().filter { it.component.isShowing() }
            if (visible.isNotEmpty()) {
                val failure = visible.last()
                assertTrue(failure.getAllTexts().any { it.text.contains(expected) })
                failure.button("Close").click()
                failuresSeen++
                lastFailure = System.nanoTime()
                false
            } else failuresSeen > 0 && System.nanoTime() - lastFailure > 1_000_000_000L
        }
    }

    private fun Driver.assertManagedEditor(path: String, text: String): Int {
        val url = "wikisource-wtbot://$path"
        waitFor("Managed editor is selected: $path", 30.seconds) {
            withContext(OnDispatcher.EDT) {
                val editor = service<FileEditorManager>(singleProject()).getSelectedTextEditor()
                editor != null && cast(editor.getVirtualFile(), ManagedTestVirtualFile::class).getUrl() == url &&
                    editor.getDocument().getText().contains(text)
            }
        }
        return withContext(OnDispatcher.EDT) {
            val editor = requireNotNull(service<FileEditorManager>(singleProject()).getSelectedTextEditor())
            val id = cast(editor.getVirtualFile(), ManagedTestFileId::class).getId()
            assertTrue(id > 0)
            assertEquals(url, requireNotNull(utility<ManagedTestManagingFs>().getInstance().findFileById(id)).getUrl())
            id
        }
    }

    private fun Driver.wikisourceWindow(): UiComponent = ui.x {
        componentWithChild(byClass("InternalDecoratorImpl"), byAccessibleName("Debug"))
    }

    private fun withProject(
        projectDirectory: Path,
        testName: String,
        runs: Int = 1,
        afterRun: (Int, Path) -> Unit = { _, _ -> },
        restoredFiles: List<String> = emptyList(),
        requestTimeoutSeconds: Int? = null,
        scenario: Driver.(String) -> Unit,
    ) {
        val preparationStarted = System.nanoTime()
        val pluginProfile = System.getProperty("wikitext.test.pluginProfile", "platform")
        require(pluginProfile in setOf("platform", "bundled")) { "Unknown IDE test plugin profile: $pluginProfile" }
        val pauseSeconds = System.getProperty("wikitext.test.pauseSeconds", "0").toLong()
        require(pauseSeconds in 0..60) { "IDE test observation pause must be between 0 and 60 seconds" }
        val fixtureText = requireNotNull(javaClass.getResource("/projects/wikitext/sample.wiki")).readText()

        projectDirectory.resolve("sample.wiki").writeText(fixtureText)

        // Seed the product workspace before opening the project. Closing Project
        // afterwards is too late to avoid 262's scheme-loading/tree-rendering race.
        val workspaceId = "0" + java.util.UUID.randomUUID().toString().replace("-", "").take(26)
        projectDirectory.resolve(".idea").createDirectories().resolve("workspace.xml").writeText(
            """<project version="4"><component name="ProjectId" id="$workspaceId" /></project>""",
        )

        val langPluginPath = System.getProperty("wikitext.language.plugin.archive")?.let { Path.of(it) }
        val remotePluginPath = System.getProperty("wikisource.remote.plugin.archive")?.let { Path.of(it) }
        val fallbackArchive = System.getProperty("path.to.build.plugin")?.let { Path.of(it) }

        val ideInfo = IdeInfo.IdeaUltimate.copy(getInstaller = { ideInstaller })

        val testContext =
            Starter.newContext(testName, TestCase(ideInfo, LocalProjectInfo(projectDirectory)))
                .apply {
                    if (langPluginPath != null && remotePluginPath != null) {
                        PluginConfigurator(this).installPluginFromPath(langPluginPath)
                        PluginConfigurator(this).installPluginFromPath(remotePluginPath)
                    } else if (fallbackArchive != null) {
                        PluginConfigurator(this).installPluginFromPath(fallbackArchive)
                    }
                    if (pluginProfile == "platform") {
                        // Exercise the free platform APIs used by Wikisource. Avoid
                        // the subscription-mode transition and unrelated language plugins.
                        disableUltimateModule()
                        applyVMOptionsPatch {
                            addSystemProperty("idea.load.plugins.id", "org.limepepper.lang.wikitext,org.limepepper.wikisource,com.jetbrains.performancePlugin")
                        }
                    }
                    val editorEntries = restoredFiles.joinToString("\n") { url ->
                        val provider = if (url.endsWith("/@props")) "text-editor" else "wikitext-preview"
                        """<file current-in-tab="true"><entry file="$url"><provider editor-type-id="$provider" selected="true" /></entry></file>"""
                    }
                    paths.configDir.resolve("workspace").createDirectories().resolve("$workspaceId.xml").writeText(
                        """
                        <project version="4">
                          <component name="FileEditorManager"><leaf>$editorEntries</leaf></component>
                          <component name="ToolWindowManager">
                            <layoutV2><window_info id="Project" order="0" visible="false" /></layoutV2>
                            <layout><window_info id="Project" order="0" visible="false" /></layout>
                          </component>
                        </project>
                        """.trimIndent(),
                    )
                    // Keep the test deterministic: 2026.2.4's default Islands theme
                    // can refer to an unavailable editor scheme during project startup.
                    paths.configDir.resolve("options").createDirectories().resolve("laf.xml").writeText(
                        """
                    <application>
                      <component name="LafManager" autodetect="false">
                        <laf class-name="com.intellij.ide.ui.laf.darcula.DarculaLaf" />
                      </component>
                    </application>
                    """.trimIndent(),
                    )
                    // Fresh 2026.2.4 settings can contain Windows/DTrace profiler
                    // defaults unavailable on Linux, making Save All log IDE errors.
                    // Seed one supported configuration; keep IDE error reporting enabled.
                    paths.configDir.resolve("options/profilerRunConfigurations.xml").writeText(
                        """
                        <application>
                          <component name="ProfilerRunConfigurations">
                            <profilerRunConfigurations>
                              <item configurationTypeId="IntellijProfilerConfiguration">
                                <IntellijProfilerConfigurationState name="IntelliJ Profiler" />
                              </item>
                            </profilerRunConfigurations>
                            <knownConfigurationTypes>
                              <id>IntellijProfilerConfiguration</id>
                              <id>AsyncProfilerCPUConfiguration</id>
                              <id>AsyncProfilerMemoryConfiguration</id>
                              <id>AsyncProfilerConfiguration</id>
                              <id>WinAsyncProfilerConfigurationType</id>
                              <id>JVMDTraceProfilerConfiguration</id>
                              <id>JFRSimpleConfiguration</id>
                            </knownConfigurationTypes>
                          </component>
                        </application>
                        """.trimIndent(),
                    )
                    // Save scenarios invoke SaveAll explicitly. Avoid competing idle
                    // and focus-loss saves opening duplicate failure dialogs.
                    paths.configDir.resolve("options/ide.general.xml").writeText(
                        """
                        <application>
                          <component name="GeneralSettings">
                            <option name="autoSaveIfInactive" value="false" />
                            <option name="saveOnFrameDeactivation" value="false" />
                          </component>
                        </application>
                        """.trimIndent(),
                    )
                    applyVMOptionsPatch {
                        addSystemProperty("idea.trust.all.projects", true)
                        addSystemProperty("ide.show.tips.on.startup.default.value", false)
                        addSystemProperty("wtbot.baseUrl", wtbot.baseUrl ?: System.getProperty("wtbot.test.baseUrl"))
                        requestTimeoutSeconds?.let { addSystemProperty("wtbot.timeoutSeconds", it) }
                    }
                }


        println("IDE timing [$testName, $pluginProfile]: preparation=${elapsedSeconds(preparationStarted)}s")
        repeat(runs) { run ->
            val launchStarted = System.nanoTime()
            var closingStarted = launchStarted
            try {
                testContext.runIdeWithDriver()
                    .useDriverAndCloseIde {
                        try {
                            val licenseInfo = ui.dialog(title = "IDE")
                            if (licenseInfo.present() && licenseInfo.getAllTexts().any { it.text == "Ultimate subscription" }) {
                                licenseInfo.button("Close").click()
                            }
                            waitForIndicators(2.minutes)
                            println("IDE timing [$testName, run=${run + 1}]: ready=${elapsedSeconds(launchStarted)}s")
                            val scenarioStarted = System.nanoTime()
                            try { scenario(fixtureText) }
                            finally {
                                println("IDE timing [$testName, run=${run + 1}]: scenario=${elapsedSeconds(scenarioStarted)}s")
                            }
                        } finally {
                            // Optional watched-run pause; keep it off the IDE's EDT.
                            if (pauseSeconds > 0) Thread.sleep(pauseSeconds * 1000)
                            closingStarted = System.nanoTime()
                        }
                    }
            } catch (t: Throwable) {
                val logFile = testContext.paths.systemDir.resolve("log/idea.log")
                if (java.nio.file.Files.exists(logFile)) {
                    println("=== IDEA LOG ===")
                    println(java.nio.file.Files.readString(logFile))
                    println("================")
                }
                throw t
            }
            println("IDE timing [$testName, run=${run + 1}]: close=${elapsedSeconds(closingStarted)}s")
            afterRun(run, testContext.paths.configDir.resolve("workspace/$workspaceId.xml"))
        }
    }

    private fun elapsedSeconds(started: Long): Double = (System.nanoTime() - started) / 1_000_000_000.0
}

@Remote("com.intellij.openapi.vfs.VirtualFileManager")
interface ManagedTestVirtualFileManager {
    fun findFileByUrl(url: String): ManagedTestVirtualFile?
    fun getFileSystem(protocol: String): ManagedTestFileSystem?
}

@Remote("com.intellij.openapi.vfs.VirtualFileSystem")
interface ManagedTestFileSystem {
    fun getProtocol(): String
}

@Remote("org.limepepper.lang.wikitext.search.WtAttachedWorkIndex", plugin = "org.limepepper.wikisource/wikisource.wikisource-remote-frontend")
interface ManagedTestWorkIndex {
    fun files(): Array<ManagedTestVirtualFile>
    fun scopes(): Array<ManagedTestGlobalScope>
}

@Remote("com.intellij.psi.search.GlobalSearchScope")
interface ManagedTestGlobalScope {
    fun getDisplayName(): String
}

@Remote("com.intellij.util.indexing.FileBasedIndex")
interface ManagedTestFileBasedIndex {
    fun getInstance(): ManagedTestFileBasedIndex
    fun getContainingFiles(index: ManagedTestIndexId, key: ManagedTestWordIndexEntry, scope: ManagedTestGlobalScope): Collection<ManagedTestVirtualFile>
}

@Remote("com.intellij.util.indexing.ID")
interface ManagedTestIndexId {
    fun findByName(name: String): ManagedTestIndexId?
}

@Remote("com.intellij.psi.impl.cache.impl.id.IdIndexEntry")
interface ManagedTestWordIndexEntry

@Remote("javax.swing.JLabel")
interface ManagedTestLabel {
    fun getText(): String
}

@Remote("com.intellij.openapi.fileEditor.FileEditorManager")
interface ManagedTestEditorManager {
    fun openFile(file: VirtualFile, focus: Boolean): Array<ManagedTestFileEditor>
    fun getOpenFiles(): Array<ManagedTestVirtualFile>
    fun getSelectedEditor(file: VirtualFile): ManagedTestFileEditor?
}

@Remote("com.intellij.openapi.fileEditor.FileEditor")
interface ManagedTestFileEditor {
    fun getName(): String
}

@Remote("com.intellij.openapi.fileEditor.FileDocumentManager")
interface ManagedTestDocumentManager {
    fun getInstance(): ManagedTestDocumentManager
    fun isDocumentUnsaved(document: Document): Boolean
    fun reloadFromDisk(document: Document)
}


@Remote("com.intellij.openapi.vfs.VirtualFile")
interface ManagedTestVirtualFile : VirtualFile {
    fun refresh(asynchronous: Boolean, recursive: Boolean)
    fun getUrl(): String
    fun isValid(): Boolean
    fun isWritable(): Boolean
    fun getLength(): Long
}

@Remote("com.intellij.openapi.vfs.VirtualFileWithId")
interface ManagedTestFileId {
    fun getId(): Int
}

@Remote("com.intellij.openapi.vfs.newvfs.ManagingFS")
interface ManagedTestManagingFs {
    fun getInstance(): ManagedTestManagingFs
    fun findFileById(id: Int): ManagedTestVirtualFile?
}
