package org.limepepper.lang.wikitext.semantics

import com.intellij.lang.LanguageParserDefinitions
import com.intellij.openapi.command.WriteCommandAction
import com.intellij.psi.PsiDocumentManager
import com.intellij.psi.PsiFileFactory
import com.intellij.psi.SmartPointerManager
import com.intellij.testFramework.LightPlatformTestCase
import org.limepepper.lang.wikitext.WtFileType
import org.limepepper.lang.wikitext.WtLanguage
import org.limepepper.lang.wikitext.parser.WtParserDefinition
import org.limepepper.lang.wikitext.psi.WtTypes

class WtSemanticViewEditingTest : LightPlatformTestCase() {
    private val parser = WtParserDefinition()

    override fun setUp() {
        super.setUp()
        LanguageParserDefinitions.INSTANCE.addExplicitExtension(WtLanguage, parser)
    }

    override fun tearDown() {
        try {
            LanguageParserDefinitions.INSTANCE.removeExplicitExtension(WtLanguage, parser)
        } finally {
            super.tearDown()
        }
    }

    fun testReclassificationAfterDocumentEditsUsesGenericPsiAndSmartPointers() {
        val file = PsiFileFactory.getInstance(project).createFileFromText("edit.wt", WtFileType, "<ref name=x/>", 0, true)
        val view = WtSemanticViews.reference(file.firstChild)!!
        val pointer = SmartPointerManager.getInstance(project).createSmartPsiElementPointer(view.source)
        val manager = PsiDocumentManager.getInstance(project)
        val document = manager.getDocument(file)!!
        WriteCommandAction.runWriteCommandAction(project) {
            document.replaceString(1, 4, "span")
            manager.commitDocument(document)
        }
        val edited = pointer.element!!
        assertEquals(WtTypes.HTML_TAG, edited.node.elementType)
        assertEquals("span", WtSemanticViews.tag(edited)!!.name)
        assertNull(WtSemanticViews.of(edited))
        WriteCommandAction.runWriteCommandAction(project) {
            document.replaceString(1, 5, "ref")
            manager.commitDocument(document)
        }
        assertEquals("x", WtSemanticViews.reference(pointer.element!!)!!.name)
    }
}
