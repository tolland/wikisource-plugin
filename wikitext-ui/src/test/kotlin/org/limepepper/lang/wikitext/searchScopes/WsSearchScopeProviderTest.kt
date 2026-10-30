package org.limepepper.lang.wikitext.searchScopes

import com.intellij.openapi.actionSystem.DataContext
import com.intellij.testFramework.fixtures.BasePlatformTestCase
import org.limepepper.lang.wikitext.vfs.backend.FakeVfsBackend
import org.limepepper.lang.wikitext.vfs.backend.ListChildrenResult
import org.limepepper.lang.wikitext.vfs.backend.StatResult
import org.limepepper.lang.wikitext.vfs.backend.VfsBackend
import org.limepepper.lang.wikitext.vfs.backend.WtVfsService

class WsSearchScopeProviderTest : BasePlatformTestCase() {
    fun testScopeChooserDoesNotContactBackendAndKeepsEmptyScopeNames() {
        val service = WtVfsService.instance
        val original = service.backend
        service.setBackendForTesting(object : VfsBackend by FakeVfsBackend() {
            override fun stat(path: String): StatResult = error("Scope chooser contacted backend: $path")
            override fun listChildren(path: String): ListChildrenResult = error("Scope chooser contacted backend: $path")
        })
        try {
            val scopes = WsSearchScopeProvider().getSearchScopes(project, DataContext.EMPTY_CONTEXT)
            assertEquals(1, scopes.size)
            scopes.forEach { scope ->
                assertNotNull(scope)
                assertTrue(scope!!.displayName.startsWith("Wikisource ("))
            }
            val empty = namedFileScope(project, emptySet(), "Wikisource (managed wtbot)")
            assertEquals("Wikisource (managed wtbot) (work unavailable)", empty.displayName)
        } finally {
            service.setBackendForTesting(original)
        }
    }
}
