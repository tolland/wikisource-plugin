@file:Suppress("UnstableApiUsage")
package org.limepepper.lang.wikitext.inlay

import com.intellij.codeInsight.hints.ChangeListener
import com.intellij.codeInsight.hints.FactoryInlayHintsCollector
import com.intellij.codeInsight.hints.ImmediateConfigurable
import com.intellij.codeInsight.hints.InlayHintsCollector
import com.intellij.codeInsight.hints.InlayHintsProvider
import com.intellij.codeInsight.hints.InlayHintsSink
import com.intellij.codeInsight.hints.NoSettings
import com.intellij.codeInsight.hints.SettingsKey
import com.intellij.openapi.editor.Editor
import com.intellij.psi.PsiElement
import com.intellij.psi.PsiFile
import org.limepepper.lang.wikitext.psi.WtTypes
import org.limepepper.lang.wikitext.tool.MyMessageBundle
import javax.swing.JPanel

class ProofreadInlayProvider : InlayHintsProvider<NoSettings> {

    override fun getCollectorFor(
        file: PsiFile,
        editor: Editor,
        settings: NoSettings,
        sink: InlayHintsSink
    ): InlayHintsCollector {
        return object : FactoryInlayHintsCollector(editor) {
            override fun collect(element: PsiElement, editor: Editor, sink: InlayHintsSink): Boolean {
                if (element.node?.elementType == WtTypes.HTML_TAG_CLOSE) {
                    sink.addInlineElement(
                        element.textRange.endOffset,
                        true,
                        factory.smallText(" dummy"),
                        false
                    )
                }

                return true
            }
        }
    }

    override fun createSettings() = NoSettings()

    override val name: String
        get() = MyMessageBundle.message("markdown.table.inlay.kind.name")

    override val description: String
        get() = MyMessageBundle.message("markdown.table.inlay.kind.description")

    @Suppress("UnstableApiUsage")
    override val key: SettingsKey<NoSettings>
        get() = settingsKey

    override val previewText: String? = null

    override fun createConfigurable(settings: NoSettings): ImmediateConfigurable {
        return object: ImmediateConfigurable {
            override fun createComponent(listener: ChangeListener) = JPanel()
        }
    }

    companion object {
        val settingsKey = SettingsKey<NoSettings>("ProofreadInlayProvider")
    }
}
