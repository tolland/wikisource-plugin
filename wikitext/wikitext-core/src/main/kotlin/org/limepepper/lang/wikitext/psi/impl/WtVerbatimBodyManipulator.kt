package org.limepepper.lang.wikitext.psi.impl

import com.intellij.openapi.util.TextRange
import com.intellij.psi.AbstractElementManipulator
import org.limepepper.lang.wikitext.psi.WtTypes
import org.limepepper.lang.wikitext.psi.WtVerbatimBody

class WtVerbatimBodyManipulator :
    AbstractElementManipulator<WtVerbatimBody>() {

    override fun getRangeInElement(
        element: WtVerbatimBody,
    ): TextRange =
        TextRange(0, element.textLength)

    override fun handleContentChange(
        element: WtVerbatimBody,
        range: TextRange,
        newContent: String,
    ): WtVerbatimBody {
        val replacementText = element.text.replaceRange(
            range.startOffset,
            range.endOffset,
            newContent,
        )

        val replacement =
            WtElementFactory.createVerbatimBody(
                element.project,
                replacementText,
            )

        return element.replace(replacement) as WtVerbatimBody
    }
}
