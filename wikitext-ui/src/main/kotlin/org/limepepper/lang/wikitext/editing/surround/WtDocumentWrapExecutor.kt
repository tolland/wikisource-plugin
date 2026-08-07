package org.limepepper.lang.wikitext.editing.surround

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.project.Project
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.util.TextRange
import org.limepepper.lang.wikitext.editing.WtEditingFlags
import org.limepepper.lang.wikitext.editing.WtWrapRenderer
import org.limepepper.lang.wikitext.editing.WtWrapTag

/**
 * The deliberately dumb [WtWrapExecutor]: one document replacement, no
 * template state machine, no in-editor popup unless asked for.
 *
 * Worth keeping around even if [WtTemplateWrapExecutor] wins, because it has no
 * way to get stuck half-finished and behaves identically for `wikisource://`
 * files and real files — it only ever touches the [com.intellij.openapi.editor.Document].
 */
class WtDocumentWrapExecutor : WtWrapExecutor {

    override fun wrap(project: Project, editor: Editor, tag: WtWrapTag): TextRange? {
        val selection = editor.selectionModel
        val start = selection.selectionStart
        val end = selection.selectionEnd
        val selectedText = editor.document.getText(TextRange(start, end))
        val indent = WtWrapRenderer.indentOfLineAt(editor.document.charsSequence, start)

        if (tag.hasVariable && WtEditingFlags.variablePromptStyle() == WtEditingFlags.VariablePromptStyle.DIALOG) {
            promptThenWrapLater(project, editor, tag, start, end, selectedText, indent)
            return null
        }

        val rendering = WtWrapRenderer.render(tag, selectedText, variableValue = null, indent = indent)
        editor.document.replaceString(start, end, rendering.text)

        // With no value supplied the placeholder is sitting in the document;
        // selecting it makes "type over it" the obvious next move. Otherwise
        // put the caret after the wrapped content.
        val firstVariable = rendering.variableRanges.firstOrNull()
        return if (firstVariable != null) {
            TextRange(start + firstVariable.first, start + firstVariable.last + 1)
        } else {
            TextRange(start + rendering.contentEnd, start + rendering.contentEnd)
        }
    }

    /**
     * The dialog path cannot run here: the platform calls surrounders inside a
     * write action, and a modal dialog must not be shown from one. So this
     * returns immediately and does the whole thing — prompt, then its own write
     * command — once the surround command has finished.
     *
     * The offsets captured above stay valid because nothing else edited the
     * document in between; if that assumption ever stops holding, this
     * interaction style is the one to delete rather than to shore up.
     */
    private fun promptThenWrapLater(
        project: Project,
        editor: Editor,
        tag: WtWrapTag,
        start: Int,
        end: Int,
        selectedText: String,
        indent: String,
    ) {
        ApplicationManager.getApplication().invokeLater({
            if (editor.isDisposed || project.isDisposed) return@invokeLater
            val value = Messages.showInputDialog(
                project,
                tag.variablePrompt,
                tag.title,
                null,
                WtWrapRenderer.DEFAULT_PLACEHOLDER,
                null,
            ) ?: return@invokeLater

            val rendering = WtWrapRenderer.render(tag, selectedText, variableValue = value, indent = indent)
            WriteCommandAction.runWriteCommandAction(project, tag.title, null, {
                editor.document.replaceString(start, end, rendering.text)
                editor.caretModel.moveToOffset(start + rendering.contentEnd)
            })
        }, project.disposed)
    }
}
