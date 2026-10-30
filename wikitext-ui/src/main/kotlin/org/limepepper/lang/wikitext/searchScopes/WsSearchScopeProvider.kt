package org.limepepper.lang.wikitext.searchScopes

import com.intellij.openapi.actionSystem.DataContext
import com.intellij.openapi.project.Project
import com.intellij.openapi.module.Module
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.util.NlsContexts
import com.intellij.psi.search.GlobalSearchScope
import com.intellij.psi.search.SearchScope
import com.intellij.psi.search.SearchScopeProvider
import org.limepepper.lang.wikitext.search.WtManagedWorkSearch

class WsSearchScopeProvider : SearchScopeProvider {
    override fun getDisplayName(): @NlsContexts.Separator String? {
        return "Wikitext Scope"
    }

    override fun getSearchScopes(
        project: Project,
        dataContext: DataContext
    ): MutableList<SearchScope?> {
        // Scope membership is separate from indexing. Use the same bounded
        // file set so Find/Replace can explicitly target this experiment.
        return mutableListOf(
            namedFileScope(project, project.getService(WtManagedWorkSearch::class.java).cachedFiles(),
                "Wikisource (managed wtbot)")
        )
    }
}

/** filesScope discards displayName when files is empty, yielding <unknown scope>. */
internal fun namedFileScope(project: Project, files: Set<VirtualFile>, name: String): GlobalSearchScope =
    if (files.isNotEmpty()) GlobalSearchScope.filesScope(project, files, name)
    else object : GlobalSearchScope(project) {
        override fun getDisplayName(): String = "$name (work unavailable)"
        override fun contains(file: VirtualFile): Boolean = false
        override fun isSearchInModuleContent(module: Module): Boolean = false
        override fun isSearchInLibraries(): Boolean = false
    }
