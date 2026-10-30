package org.limepepper.lang.wikitext.searchScopes

import com.intellij.openapi.module.Module
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.psi.search.GlobalSearchScope

class WsSearchScopeWithName(searchScope: GlobalSearchScope, name: String) : GlobalSearchScope() {

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
