package org.limepepper.lang.wikitext.templates

import com.intellij.codeInsight.template.TemplateActionContext
import com.intellij.codeInsight.template.TemplateContextType
import org.limepepper.lang.wikitext.WtLanguage

class WtContextType : TemplateContextType("Wikitext") {
    /**
     * Match on the PSI file's language rather than a `.wt` file-name suffix:
     * wikisource:// VFS pages are named after their wiki title (`Page:….djvu/12`,
     * no extension) but still parse as Wikitext via their content model, and a
     * name check silently excluded them from live templates.
     */
    override fun isInContext(templateActionContext: TemplateActionContext): Boolean {
        return templateActionContext.file.language.isKindOf(WtLanguage)
    }
}
