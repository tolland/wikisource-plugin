package org.limepepper.lang.wikitext

import com.intellij.icons.AllIcons
import com.intellij.openapi.fileTypes.LanguageFileType
import javax.swing.Icon

/**
 * File type definition for generic WikiText markup files
 */
object PrpFileType : LanguageFileType(WtLanguage) {

    override fun getName() = "proofread-page"

    override fun getDisplayName() = "Proofread Page"

    override fun getDescription() = "Wikisource Proofread Page markup file"

    override fun getDefaultExtension() = "prp"

    override fun getIcon(): Icon = AllIcons.Actions.Lightning
}
