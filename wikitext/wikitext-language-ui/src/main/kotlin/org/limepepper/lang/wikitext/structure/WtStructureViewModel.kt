package org.limepepper.lang.wikitext.structure

import com.intellij.ide.structureView.StructureViewModel
import com.intellij.ide.structureView.StructureViewModelBase
import com.intellij.ide.structureView.StructureViewTreeElement
import com.intellij.ide.util.treeView.smartTree.Sorter
import com.intellij.openapi.editor.Editor
import com.intellij.psi.PsiFile
import org.limepepper.lang.wikitext.psi.WtHeading
import org.limepepper.lang.wikitext.psi.WtInternalLink
import org.limepepper.lang.wikitext.psi.WtTemplate
import kotlin.jvm.java


class WtStructureViewModel(
    psiFile: PsiFile,
    editor: Editor?
) :
    StructureViewModelBase(
        psiFile,
        editor,
        WtStructureViewElement(psiFile)
    ),
    StructureViewModel.ElementInfoProvider {

    override fun isAlwaysShowsPlus(element: StructureViewTreeElement): Boolean = false

    override fun isAlwaysLeaf(element: StructureViewTreeElement): Boolean = false

    override fun getSorters(): Array<Sorter> {
        return arrayOf(Sorter.ALPHA_SORTER)
    }

    override fun getSuitableClasses(): Array<Class<*>> {
        return arrayOf(
            WtHeading::class.java,
            WtInternalLink::class.java,
            WtTemplate::class.java
        )
    }
}
