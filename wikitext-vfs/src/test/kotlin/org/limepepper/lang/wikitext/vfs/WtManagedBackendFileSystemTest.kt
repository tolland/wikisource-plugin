package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.editor.ex.DocumentEx
import com.intellij.psi.PsiManager
import com.intellij.find.FindManager
import com.intellij.find.FindModel
import com.intellij.find.impl.FindResultUsageInfo
import com.intellij.find.replaceInProject.ReplaceInProjectManager
import com.intellij.usages.UsageInfo2UsageAdapter
import com.intellij.util.ui.UIUtil
import com.intellij.openapi.vfs.VirtualFileWithId
import com.intellij.openapi.vfs.newvfs.ManagingFS
import com.intellij.openapi.vfs.newvfs.NewVirtualFile
import com.intellij.testFramework.fixtures.BasePlatformTestCase
import org.limepepper.lang.wikitext.vfs.backend.FakeVfsBackend
import org.limepepper.lang.wikitext.vfs.backend.NodeKind
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import org.limepepper.lang.wikitext.vfs.backend.VfsBackendException
import org.limepepper.lang.wikitext.vfs.backend.WriteResult
import org.limepepper.lang.wikitext.vfs.backend.WriteStatus
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
        assertEquals(path, WtWikiFiles.pathOf(file))
        assertEquals("wikitext", WtWikiFiles.contentModelOf(file))
        assertEquals(41L, WtWikiFiles.revisionOf(file))
        assertNull(WtWikiFiles.pathOf(myFixture.tempDirFixture.createFile("local.wiki")))
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


    fun testNativeReplacementSavesManagedDocument() {
        val path = testPath("managed-replace")
        val backend = fake(path)
        WtVfsService.instance.setBackendForTesting(backend)
        val managed = requireNotNull(fileSystem.findFileByPath(path))
        val documents = FileDocumentManager.getInstance()
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
        assertEquals("Initial ambitions.", managedDocument.text)
        assertFalse(documents.isDocumentUnsaved(managedDocument))
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
        assertEquals(41L, WtWikiFiles.revisionOf(file))
        val failure = runCatching {
            fs.getOutputStream(file, this, 0, 0).use { it.write("Stale edit".toByteArray()) }
        }.exceptionOrNull()
        assertTrue(failure is IOException)
        assertTrue(failure?.message.orEmpty().contains("conflict"))
        assertEquals("Remote edit", backend.readContent(path).decodeText())
    }

    fun testPersistentContentRevisionSurvivesAdapterRestart() {
        val path = testPath("managed-persistent-revision")
        val base = fake(path)
        val backend = object : VfsBackend by base {
            override val cacheIdentity = "test-owned-persistent-backend"
        }
        WtVfsService.instance.setBackendForTesting(backend)
        val file = requireNotNull(fileSystem.findFileByPath(path))
        fileSystem.contentsToByteArray(file)
        val restarted = WtManagedBackendFileSystem()
        assertEquals("wikitext", restarted.cachedMetadata(file)?.contentModel)
        backend.writeContent(path, Base64.getEncoder().encodeToString("External edit".toByteArray()), 41)
        assertEquals(41L, restarted.cachedContentRevision(file))
        val failure = runCatching {
            restarted.getOutputStream(file, this, 0, 0).use { it.write("Stale edit".toByteArray()) }
        }.exceptionOrNull()
        assertTrue(failure is IOException)
        assertEquals("External edit", backend.readContent(path).decodeText())
    }

    fun testRefreshReadPreservesUnsavedDocumentRevision() {
        val path = testPath("managed-unsaved-refresh")
        val backend = fake(path)
        WtVfsService.instance.setBackendForTesting(backend)
        val file = requireNotNull(fileSystem.findFileByPath(path))
        val documents = FileDocumentManager.getInstance()
        val document = requireNotNull(documents.getDocument(file))
        try {
            WriteCommandAction.runWriteCommandAction(project) { document.setText("Local unsaved edit") }
            // PersistentFS can align the stamps on a failed save while the
            // Document still belongs to the unsaved set. Do not trust stamp equality.
            (document as DocumentEx).setModificationStamp(file.modificationStamp)
            assertTrue(documents.isDocumentUnsaved(document))
            backend.writeContent(path, Base64.getEncoder().encodeToString("External edit".toByteArray()), 41)
            assertEquals("External edit", String(fileSystem.contentsToByteArray(file)))
            assertEquals("Local unsaved edit", document.text)
            assertEquals(41L, WtWikiFiles.revisionOf(file))
            val failure = runCatching {
                fileSystem.getOutputStream(file, this, 0, 0).use { it.write(document.text.toByteArray()) }
            }.exceptionOrNull()
            assertTrue(failure is IOException)
            assertEquals("External edit", backend.readContent(path).decodeText())
        } finally {
            documents.reloadFromDisk(document)
        }
    }

    fun testRefreshSeesExternalContent() {
        val path = testPath("managed-refresh")
        val backend = fake(path)
        WtVfsService.instance.setBackendForTesting(backend)
        val fs = fileSystem
        val file = requireNotNull(fs.findFileByPath(path))
        assertEquals("Initial aspirations.", String(file.contentsToByteArray()))
        (file as NewVirtualFile).markClean()
        backend.writeContent(path, Base64.getEncoder().encodeToString("External edit".toByteArray()), 41)
        fs.refreshFile(file, false)
        assertEquals("External edit", String(file.contentsToByteArray()))
    }

    fun testUnavailableRefreshPreservesCachedDocumentAndRecovers() {
        val path = testPath("managed-outage")
        val base = fake(path)
        var available = true
        val backend = object : VfsBackend by base {
            override fun stat(path: String) = if (available) base.stat(path)
                else throw VfsBackendException("Connection refused")
        }
        WtVfsService.instance.setBackendForTesting(backend)
        val file = requireNotNull(fileSystem.findFileByPath(path))
        val id = (file as VirtualFileWithId).id
        val document = requireNotNull(FileDocumentManager.getInstance().getDocument(file))
        available = false
        val root = requireNotNull(fileSystem.findFileByPath("/"))
        assertTrue(fileSystem.exists(root))
        assertTrue(fileSystem.isDirectory(root))
        assertTrue(runCatching { fileSystem.refreshFile(file, false) }.exceptionOrNull() is IOException)
        assertNotNull(fileSystem.getAttributes(file))
        // An IDE-initiated refresh of an already-known file must also survive.
        (file as NewVirtualFile).markDirty()
        file.refresh(false, false)
        assertTrue(file.isValid)
        assertEquals("Initial aspirations.", document.text)
        val cached = requireNotNull(fileSystem.findFileByPath(path))
        assertEquals(id, (cached as VirtualFileWithId).id)
        assertSame(document, FileDocumentManager.getInstance().getDocument(cached))
        available = true
        backend.writeContent(path, Base64.getEncoder().encodeToString("Recovered edit".toByteArray()), 41)
        fileSystem.refreshFile(file, false)
        UIUtil.dispatchAllInvocationEvents()
        assertEquals(id, (file as VirtualFileWithId).id)
        assertEquals("Recovered edit", document.text)
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

    fun testGlobalRefreshOnlyVisitsKnownPhysicalFiles() {
        val path = testPath("bounded-refresh")
        val base = fake(path)
        var directoryListings = 0
        val backend = object : VfsBackend by base {
            override fun listChildren(path: String) = base.listChildren(path).also { directoryListings++ }
        }
        WtVfsService.instance.setBackendForTesting(backend)
        val file = requireNotNull(fileSystem.findFileByPath(path))
        val document = requireNotNull(FileDocumentManager.getInstance().getDocument(file))
        backend.writeContent(path, Base64.getEncoder().encodeToString("Refreshed known file".toByteArray()), 41)
        directoryListings = 0
        fileSystem.refresh(false)
        UIUtil.dispatchAllInvocationEvents()
        assertEquals(0, directoryListings)
        assertEquals("Refreshed known file", document.text)
    }

    fun testEndpointRebindReloadsSameMetadataFromNewConnection() {
        val path = testPath("connection-rebind")
        val base = fake(path)
        fun connection(url: String, text: String) = object : VfsBackend by base {
            override val cacheIdentity = url
            override val requiresDatabaseIdentity = true
            override fun stat(path: String) = base.stat(path).copy(databaseId = "shared-database")
            override fun readContent(path: String) = base.readContent(path).copy(databaseId = "shared-database",
                contentBase64 = Base64.getEncoder().encodeToString(text.toByteArray()))
        }
        WtVfsService.instance.setBackendForTesting(connection("first-url", "Initial aspirations."))
        val file = requireNotNull(fileSystem.findFileByPath(path))
        val document = requireNotNull(FileDocumentManager.getInstance().getDocument(file))
        WtVfsService.instance.setBackendForTesting(connection("second-url", "Initial definitions."))
        fileSystem.resetConnection(file)
        fileSystem.refreshFile(file, false)
        UIUtil.dispatchAllInvocationEvents()
        assertEquals("Initial definitions.", document.text)
    }

    fun testDatabaseReplacementWithIdenticalMetadataReloadsCleanDocument() {
        val path = testPath("database-identity")
        val base = fake(path)
        var databaseId = "first"
        var text = "Initial aspirations."
        val backend = object : VfsBackend by base {
            override val cacheIdentity = "test-database-identity"
            override val requiresDatabaseIdentity = true
            override fun stat(path: String) = base.stat(path).copy(databaseId = databaseId)
            override fun readContent(path: String) = base.readContent(path).copy(
                databaseId = databaseId, contentBase64 = Base64.getEncoder().encodeToString(text.toByteArray()))
            override fun writeContent(path: String, contentBase64: String, baseRevid: Long?, comment: String?, databaseId: String?): WriteResult {
                if (databaseId != this.readContent(path).databaseId) throw VfsBackendException("Database changed")
                text = String(Base64.getDecoder().decode(contentBase64))
                return WriteResult(path, WriteStatus.ok, 41, databaseId = databaseId)
            }
        }
        WtVfsService.instance.setBackendForTesting(backend)
        val file = requireNotNull(fileSystem.findFileByPath(path))
        val documents = FileDocumentManager.getInstance()
        val document = requireNotNull(documents.getDocument(file))
        val id = (file as VirtualFileWithId).id
        val before = backend.stat(path)
        databaseId = "second"
        text = "Initial definitions."
        assertEquals(before.timestamp, backend.stat(path).timestamp)
        assertEquals(before.length, backend.stat(path).length)
        fileSystem.refreshFile(file, false)
        UIUtil.dispatchAllInvocationEvents()
        assertEquals(text, document.text)
        assertEquals(id, (file as VirtualFileWithId).id)
        try {
            WriteCommandAction.runWriteCommandAction(project) { document.setText("Unsaved text from second database") }
            databaseId = "third"
            assertTrue(runCatching {
                fileSystem.getOutputStream(file, this, 0, 0).use { it.write(document.text.toByteArray()) }
            }.exceptionOrNull() is IOException)
            assertEquals("Initial definitions.", text)
            assertTrue(documents.isDocumentUnsaved(document))
        } finally { documents.reloadFromDisk(document) }
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
