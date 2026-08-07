package org.limepepper.lang.wikitext.editing.surround

import com.intellij.codeInsight.template.TemplateManager
import com.intellij.codeInsight.template.impl.ConstantNode
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.TextRange
import org.limepepper.lang.wikitext.editing.WtWrapRenderer
import org.limepepper.lang.wikitext.editing.WtWrapTag

/**
 * The platform-idiomatic [WtWrapExecutor]: inserts the markup as a live
 * template so a construct's value is typed straight into the document.
 *
 * This is the whole reason [WtWrapTag.SECTION] is tractable without a dialog.
 * Its begin and end markers must carry the *same* name, and a live template
 * mirrors repeated occurrences of a variable automatically — type the section
 * name once and both `<section begin="…"/>` and `<section end="…"/>` update as
 * you go.
 */
class WtTemplateWrapExecutor : WtWrapExecutor {

    override fun wrap(project: Project, editor: Editor, tag: WtWrapTag): TextRange? {
        val selection = editor.selectionModel
        val selectedText = editor.document.getText(TextRange(selection.selectionStart, selection.selectionEnd))
        val indent = WtWrapRenderer.indentOfLineAt(editor.document.charsSequence, selection.selectionStart)

        // Render with the selection standing in as the template's $SELECTION$
        // segment, leaving the tag's own $NAME$ placeholder in place: the
        // rendered string *is* valid template text, so the markup here is
        // guaranteed identical to what the document executor produces.
        val templateText = WtWrapRenderer.render(
            tag,
            selection = SELECTION_VARIABLE,
            variableValue = WtWrapTag.VARIABLE,
            indent = indent,
        ).text

        val template = TemplateManager.getInstance(project).createTemplate("", "", templateText)
        template.isToReformat = false
        // Called rather than assigned: Template exposes only the setter, so
        // there is no Kotlin property to assign to. Both flags are off because
        // WtWrapRenderer has already placed the indentation exactly where it
        // wants it, and letting the template engine re-indent would double it.
        template.setToIndent(false)
        if (tag.hasVariable) {
            template.addVariable(NAME_VARIABLE, ConstantNode(WtWrapRenderer.DEFAULT_PLACEHOLDER), true)
        }

        TemplateManager.getInstance(project).startTemplate(editor, selectedText, template)
        // The template owns the caret from here; nothing for the platform to select.
        return null
    }

    private companion object {
        /** Platform-reserved template variable that expands to the selection. */
        const val SELECTION_VARIABLE = "\$SELECTION$"

        /** Must match the variable inside [WtWrapTag.VARIABLE]. */
        const val NAME_VARIABLE = "NAME"
    }
}
