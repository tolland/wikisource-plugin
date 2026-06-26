package org.limepepper.lang.wikitext.templates

import com.intellij.codeInsight.template.TemplateActionContext
import com.intellij.codeInsight.template.TemplateContextType
import org.jetbrains.annotations.NotNull


class WtContextType : TemplateContextType("Wikitext") {
    override fun isInContext(@NotNull templateActionContext: TemplateActionContext): Boolean {
        return templateActionContext.getFile().getName().endsWith(".wt")
    }
}