package org.limepepper.lang.wikitext

import com.intellij.icons.AllIcons
import com.intellij.openapi.fileTypes.LanguageFileType
import javax.swing.Icon

/**
 * File type definition for generic WikiText markup files
 */
object WtFileType : LanguageFileType(WtLanguage) {

    override fun getName() = "Wikitext"

    override fun getDescription() = "Wikitext markup file"

    override fun getDefaultExtension() = "wt"

    override fun getIcon(): Icon = AllIcons.Actions.StartDebugger
}
