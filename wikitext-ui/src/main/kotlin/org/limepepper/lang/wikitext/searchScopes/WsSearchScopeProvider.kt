package org.limepepper.lang.wikitext.searchScopes

import com.intellij.openapi.actionSystem.DataContext
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.NlsContexts
import com.intellij.psi.search.SearchScope
import com.intellij.psi.search.SearchScopeProvider
import com.intellij.psi.search.GlobalSearchScope
import org.limepepper.lang.wikitext.search.WtStaticSearchFiles
import org.limepepper.lang.wikitext.search.managedDemoFiles

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
        return mutableListOf(GlobalSearchScope.filesScope(
            project, WtStaticSearchFiles.resolve(), "Wikisource (static indexing demo)"
        ), GlobalSearchScope.filesScope(project, managedDemoFiles(), "Wikisource (managed VFS demo)"))
    }
}
