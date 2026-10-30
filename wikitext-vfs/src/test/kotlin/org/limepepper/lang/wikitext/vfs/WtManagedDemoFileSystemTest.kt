package org.limepepper.lang.wikitext.vfs

import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.vfs.VirtualFileWithId
import com.intellij.openapi.vfs.newvfs.ManagingFS
import com.intellij.testFramework.fixtures.BasePlatformTestCase

class WtManagedDemoFileSystemTest : BasePlatformTestCase() {
    fun testManagedIdentityAndSave() {
        // Module-only tests do not load the root plugin's module descriptors.
        val fileSystem = WtManagedDemoFileSystem()
        val file = requireNotNull(fileSystem.findFileByPath(WtManagedDemoFileSystem.FILE_PATH))
        val id = (file as VirtualFileWithId).id
        assertTrue(id > 0)
        // Managed VFS may return distinct wrapper instances for the same record.
        assertEquals(file, ManagingFS.getInstance().findFileById(id))
        assertEquals(file, requireNotNull(file.parent).findChild("probe.txt"))

        val original = file.contentsToByteArray()
        try {
            WriteCommandAction.runWriteCommandAction(project) {
                file.setBinaryContent("Replacement aspirations.\n".toByteArray())
            }
            assertEquals("Replacement aspirations.\n", String(file.contentsToByteArray()))
            val fs = file.fileSystem as WtManagedDemoFileSystem
            assertEquals("Replacement aspirations.\n", String(fs.contentsToByteArray(file)))
            assertEquals(file, ManagingFS.getInstance().findFileById(id))
        } finally {
            WriteCommandAction.runWriteCommandAction(project) { file.setBinaryContent(original) }
        }
    }
}
