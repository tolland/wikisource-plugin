package org.limepepper.lang.wikitext.psi

import com.intellij.extapi.psi.PsiFileBase
import com.intellij.openapi.fileTypes.FileType
import com.intellij.psi.FileViewProvider
import com.intellij.psi.util.PsiTreeUtil
import org.limepepper.lang.wikitext.WtFileType
import org.limepepper.lang.wikitext.WtLanguage

class WtFile(viewProvider: FileViewProvider) : PsiFileBase(viewProvider, WtLanguage) {

//    val commands: Collection<WtContentElement>
//        get() = PsiTreeUtil.findChildrenOfType(this, WtContentElement::class.java)

    override fun getFileType(): FileType = WtFileType

    override fun toString(): String = "Wikitext File"

}
