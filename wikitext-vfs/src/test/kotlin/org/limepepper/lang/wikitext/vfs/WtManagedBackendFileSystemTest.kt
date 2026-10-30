package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.psi.PsiManager
import com.intellij.find.FindManager
import com.intellij.find.FindModel
import com.intellij.find.impl.FindResultUsageInfo
import com.intellij.find.replaceInProject.ReplaceInProjectManager
import com.intellij.usages.UsageInfo2UsageAdapter
import com.intellij.util.ui.UIUtil
import com.intellij.openapi.vfs.VirtualFileWithId
import com.intellij.openapi.vfs.newvfs.ManagingFS
import com.intellij.testFramework.fixtures.BasePlatformTestCase
import org.limepepper.lang.wikitext.vfs.backend.FakeVfsBackend
import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService
import java.io.IOException
import java.util.Base64
import java.util.UUID

class WtManagedBackendFileSystemTest : BasePlatformTestCase() {
    private lateinit var originalBackend: VfsBackend

    override fun setUp() {
        super.setUp()
        originalBackend = WtVfsService.instance.backend
    }

    override fun tearDown() {
        try { WtVfsService.instance.setBackendForTesting(originalBackend) }
        finally { super.tearDown() }
    }

    // Persistent VFS records survive test JVMs, but each fake backend starts fresh.
    // Never bind a new fixture to a previous run's cached contents or permissions.
    private fun testPath(name: String): String =
        "/mywikisource/en/Page/$name-${UUID.randomUUID()}/@wikitext"

    private fun fake(path: String): VfsBackend {
        // Mirror the API: / lists a site directly; the /family node is missing.
        val fake = FakeVfsBackend().addDirectory("/").addDirectory("/mywikisource/en", parent = "/")
            .addDirectory("/mywikisource/en/Page")
            .addDirectory(path.substringBeforeLast('/'))
            .addFile(path, "Initial aspirations.", revid = 41, contentModel = "wikitext")
        // Model timestamps so the platform can detect writes and external revisions.
        return object : VfsBackend by fake {
            override fun stat(path: String) = fake.stat(path).let {
                it.copy(timestamp = ((it.revid ?: 0L) * 1000).toString())
            }
            override fun statBulk(paths: List<String>) = paths.map(::stat)
        }
    }

    fun testManagedBackendReadAndSave() {
        val path = testPath("managed-save")
        val backend = fake(path)
        WtVfsService.instance.setBackendForTesting(backend)
        val fs = fileSystem
        val file = requireNotNull(fs.findFileByPath(path))
        assertFalse(backend.stat("/mywikisource").exists)
        assertNotNull(fs.findFileByPath("/mywikisource"))
        assertEquals(file, ManagingFS.getInstance().findFileById((file as VirtualFileWithId).id))
        assertEquals("Initial aspirations.", String(file.contentsToByteArray()))
        assertEquals("wikitext", fs.cachedMetadata(file)?.contentModel)
        WriteCommandAction.runWriteCommandAction(project) {
            file.setBinaryContent("Changed aspirations.".toByteArray())
        }
        assertEquals("Changed aspirations.", backend.readContent(path).decodeText())
        assertEquals("Changed aspirations.", String(file.contentsToByteArray()))
    }

    fun testPermissionRefreshMakesCachedDocumentWritable() {
        val path = testPath("managed-permissions")
        val base = fake(path)
        var writable = false
        val backend = object : VfsBackend by base {
            override fun stat(path: String) = base.stat(path).let {
                if (it.kind == NodeKind.file) it.copy(writable = writable) else it
            }
        }
        WtVfsService.instance.setBackendForTesting(backend)
        val file = requireNotNull(fileSystem.findFileByPath(path))
        val document = requireNotNull(FileDocumentManager.getInstance().getDocument(file))
        assertFalse(file.isWritable)
        assertFalse(document.isWritable)
        writable = true
        file.refresh(false, false)
        assertTrue(file.isWritable)
        assertTrue(document.isWritable)
    }


    fun testNativeReplacementSavesAndLegacyRefreshReloadsDocument() {
        val path = testPath("managed-replace")
        val backend = fake(path)
        WtVfsService.instance.setBackendForTesting(backend)
        val managed = requireNotNull(fileSystem.findFileByPath(path))
        val legacyFs = WtVirtualFileSystem()
        val legacy = requireNotNull(legacyFs.findFileByPath(path))
        val documents = FileDocumentManager.getInstance()
        val legacyDocument = requireNotNull(documents.getDocument(legacy))
        val managedDocument = requireNotNull(documents.getDocument(managed))
        assertTrue(managedDocument.isWritable)
        val psi = requireNotNull(PsiManager.getInstance(project).findFile(managed))
        val model = FindModel().apply {
            stringToFind = "aspirations"
            stringToReplace = "ambitions"
            isReplaceState = true
        }
        val finder = FindManager.getInstance(project)
        val match = finder.findString(managedDocument.text, 0, model, managed)
        assertTrue(match.isStringFound)

        val usage = UsageInfo2UsageAdapter(FindResultUsageInfo(finder, psi, 0, model, match))
        WriteCommandAction.runWriteCommandAction(project) {
            assertTrue(ReplaceInProjectManager.getInstance(project).replaceUsage(usage, model, emptySet(), false))
        }
        documents.saveDocument(managedDocument)
        assertEquals("Initial ambitions.", backend.readContent(path).decodeText())
        // Module-only tests use a manually created legacy filesystem; exercise
        // the same refresh hook called by managed saves in the registered IDE.
        legacyFs.refreshCachedPath(path, asynchronous = false)
        UIUtil.dispatchAllInvocationEvents()
        assertEquals("Initial ambitions.", legacyDocument.text)
    }

    fun testLegacyRefreshPreservesUnsavedEdits() {
        val path = testPath("legacy-unsaved")
        val backend = fake(path)
        WtVfsService.instance.setBackendForTesting(backend)
        val legacyFs = WtVirtualFileSystem()
        val legacy = requireNotNull(legacyFs.findFileByPath(path))
        val documents = FileDocumentManager.getInstance()
        val document = requireNotNull(documents.getDocument(legacy))
        try {
            WriteCommandAction.runWriteCommandAction(project) { document.setText("Unsaved local edit") }
            backend.writeContent(path, Base64.getEncoder().encodeToString("Managed replacement".toByteArray()), 41)
            legacyFs.refreshCachedPath(path, asynchronous = false)
            UIUtil.dispatchAllInvocationEvents()
            assertEquals("Unsaved local edit", document.text)
            assertEquals(41L, (legacy as WtVirtualFile).revid)
            assertTrue(documents.isDocumentUnsaved(document))
        } finally {
            documents.reloadFromDisk(document)
        }
    }

    fun testRemoteChangeConflictsWithReadRevision() {
        val path = testPath("managed-conflict")
        val backend = fake(path)
        WtVfsService.instance.setBackendForTesting(backend)
        val fs = fileSystem
        val file = requireNotNull(fs.findFileByPath(path))
        fs.contentsToByteArray(file)
        backend.writeContent(path, Base64.getEncoder().encodeToString("Remote edit".toByteArray()), 41)
        // A fresh stat must not overwrite the revision associated with the editor's read.
        fs.getAttributes(file)
        val failure = runCatching {
            fs.getOutputStream(file, this, 0, 0).use { it.write("Stale edit".toByteArray()) }
        }.exceptionOrNull()
        assertTrue(failure is IOException)
        assertTrue(failure?.message.orEmpty().contains("conflict"))
        assertEquals("Remote edit", backend.readContent(path).decodeText())
    }

    fun testRefreshSeesExternalContent() {
        val path = testPath("managed-refresh")
        val backend = fake(path)
        WtVfsService.instance.setBackendForTesting(backend)
        val fs = fileSystem
        val file = requireNotNull(fs.findFileByPath(path))
        assertEquals("Initial aspirations.", String(file.contentsToByteArray()))
        backend.writeContent(path, Base64.getEncoder().encodeToString("External edit".toByteArray()), 41)
        file.refresh(false, false)
        assertEquals("External edit", String(file.contentsToByteArray()))
    }

    fun testBackendSwitchRefusesStaleSave() {
        val path = testPath("managed-switch")
        WtVfsService.instance.setBackendForTesting(fake(path))
        val fs = fileSystem
        val file = requireNotNull(fs.findFileByPath(path))
        fs.contentsToByteArray(file)
        val replacement = fake(path)
        WtVfsService.instance.setBackendForTesting(replacement)
        val failure = runCatching { fs.getOutputStream(file, this, 0, 0) }.exceptionOrNull()
        assertTrue(failure is IOException)
        assertEquals("Initial aspirations.", replacement.readContent(path).decodeText())
    }

    fun testAddressRoundTrip() {
        val address = WtManagedAddress.fromPath("/mywikisource/en/Index/Book with spaces.pdf/@pages")
        assertEquals(address, WtManagedAddress.fromUrl(address.url))
        assertEquals("/", address.rootPath)
    }

    companion object {
        // ManagingFS retains its filesystem instance with the root, as in a running IDE.
        private val fileSystem = WtManagedBackendFileSystem()
    }
}
