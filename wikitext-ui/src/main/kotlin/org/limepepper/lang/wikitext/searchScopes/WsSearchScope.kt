package org.limepepper.lang.wikitext.searchScopes

import com.intellij.openapi.module.Module
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.psi.search.GlobalSearchScope

class WsSearchScope(project: Project): GlobalSearchScope() {
    private var onlyFilesFromThisProject = false
    private var excludeSymLinks = false

    override fun isSearchInModuleContent(aModule: Module): Boolean {
        TODO("Not yet implemented")
    }

    override fun isSearchInLibraries(): Boolean {
        TODO("Not yet implemented")
    }

    override fun contains(file: VirtualFile): Boolean {
        TODO("Not yet implemented")
    }

}
