package org.limepepper.lang.wikitext.psi.impl

import com.intellij.openapi.project.Project
import com.intellij.psi.PsiFileFactory
import com.intellij.psi.util.PsiTreeUtil
import org.limepepper.lang.wikitext.WtLanguage
import org.limepepper.lang.wikitext.psi.WtVerbatimBody

object WtElementFactory {

    fun createVerbatimBody(
        project: Project,
        content: String,
    ): WtVerbatimBody {
        val source = "<math>$content</math>"

        val file = PsiFileFactory.getInstance(project)
            .createFileFromText(
                "__verbatim_fragment__.wt",
                WtLanguage,
                source,
                false,
                false,
            )

        return PsiTreeUtil.findChildOfType(
            file,
            WtVerbatimBody::class.java,
        ) ?: error(
            "Failed to create WtVerbatimBody from: $source"
        )
    }

}
