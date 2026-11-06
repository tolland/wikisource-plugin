package org.limepepper.lang.wikitext.search

import com.intellij.openapi.actionSystem.DataContext
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.psi.search.SearchScope
import com.intellij.psi.search.SearchScopeProvider
import com.intellij.util.indexing.IndexableSetContributor

/** Individual canonical leaves only: returning directories would visit default-only pages. */
class WtAttachedWorkIndexableSetContributor : IndexableSetContributor() {
    override fun getAdditionalRootsToIndex(): Set<VirtualFile> = emptySet()
    override fun getAdditionalProjectRootsToIndex(project: Project): Set<VirtualFile> =
        project.getService(WtAttachedWorkIndex::class.java).files().toSet()
    override fun getDebugName(): String = "Wikisource attached work text"
}

/** File scopes are a first integration point; body-aware replacement is a separate operation. */
class WtAttachedWorkSearchScopeProvider : SearchScopeProvider {
    override fun getDisplayName(): String = "Wikisource works"
    override fun getSearchScopes(project: Project, dataContext: DataContext): List<SearchScope> =
        project.getService(WtAttachedWorkIndex::class.java).scopes().toList()
}
