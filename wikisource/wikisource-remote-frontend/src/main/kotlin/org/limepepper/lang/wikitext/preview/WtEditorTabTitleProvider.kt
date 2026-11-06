package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.fileEditor.impl.EditorTabTitleProvider
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import org.limepepper.lang.wikitext.vfs.WtPaths
import org.limepepper.lang.wikitext.vfs.WtWikiFiles

/** Managed files keep their physical aspect name; tabs identify the wiki title. */
class WtEditorTabTitleProvider : EditorTabTitleProvider {
    override fun getEditorTabTitle(project: Project, file: VirtualFile): String? {
        val path = WtWikiFiles.pathOf(file) ?: return null
        return if (WtPaths.aspectOf(path) != null) WtPaths.displayName(path) else null
    }
}
