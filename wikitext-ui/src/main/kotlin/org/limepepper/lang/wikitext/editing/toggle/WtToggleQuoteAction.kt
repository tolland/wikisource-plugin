package org.limepepper.lang.wikitext.editing.toggle

import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.editor.Editor
import com.intellij.psi.PsiFile
import org.limepepper.lang.wikitext.WtLanguage
import org.limepepper.lang.wikitext.editing.WtEditingFlags
import org.limepepper.lang.wikitext.editing.WtQuoteStyle
import org.limepepper.lang.wikitext.editing.WtQuoteToggle

/**
 * Adds or removes quote markup around the selection — Ctrl+B / Ctrl+I.
 *
 * The editing itself lives in
 * [org.limepepper.lang.wikitext.editing.WtQuoteToggle]; this class is only the
 * IDE plumbing. Works identically on plain `.wt` files and `wikisource://`
 * files: it touches nothing but the Document.
 *
 * ## Sharing shortcuts with the platform
 *
 * Ctrl+B is Go To Declaration and Ctrl+I is Implement Methods. Two things keep
 * that from being a fight:
 *
 * 1. [update] disables this action outside wikitext, so in every other file
 *    the platform action is the only candidate and behaves normally.
 * 2. [WtEditingActionPromoter] puts this action first when the context *is*
 *    wikitext. Without it the winner among equally-enabled candidates is not
 *    defined, which is the classic cause of "my shortcut works sometimes".
 *
 * Both are off when `wikitext.editing.toggle.enabled` is false, so the
 * keybinding can be handed back to the platform from a running IDE.
 */
abstract class WtToggleQuoteAction(private val style: WtQuoteStyle) : AnAction() {

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT

    override fun update(event: AnActionEvent) {
        val enabled = WtEditingFlags.toggleEnabled() && isWikitext(event)
        // Hidden rather than merely disabled: a greyed-out "Bold" in the Edit
        // menu of a Java file would be noise, and hiding also keeps this out
        // of the promoter's way.
        event.presentation.isEnabledAndVisible = enabled
    }

    override fun actionPerformed(event: AnActionEvent) {
        val editor = event.getData(CommonDataKeys.EDITOR) ?: return
        val project = event.project ?: return
        if (!isWikitext(event)) return

        val document = editor.document
        val caret = editor.caretModel.currentCaret
        val selectionStart = caret.selectionStart
        val selectionEnd = caret.selectionEnd

        val firstLine = document.getLineNumber(selectionStart)
        val lastLine = document.getLineNumber(selectionEnd)
        val lines = (firstLine..lastLine).map {
            document.getLineStartOffset(it)..document.getLineEndOffset(it).coerceAtLeast(document.getLineStartOffset(it))
        }

        val result = WtQuoteToggle.toggleRange(
            document.charsSequence,
            lines,
            selectionStart,
            selectionEnd,
            style,
        )
        if (result.isEmpty) return

        WriteCommandAction.runWriteCommandAction(project, templatePresentation.text, null, {
            // Descending order, so each replacement leaves earlier offsets valid.
            for (edit in result.edits) {
                document.replaceString(edit.start, edit.end, edit.replacement)
            }
            caret.setSelection(result.selectionStart, result.selectionEnd)
            caret.moveToOffset(result.selectionEnd)
        })
    }

    private fun isWikitext(event: AnActionEvent): Boolean {
        if (event.getData(CommonDataKeys.EDITOR) == null) return false
        val file: PsiFile = event.getData(CommonDataKeys.PSI_FILE) ?: return false
        return file.language.isKindOf(WtLanguage)
    }
}

/** Ctrl+B — wraps the selection in `'''`. */
class WtToggleBoldAction : WtToggleQuoteAction(WtQuoteStyle.BOLD)

/** Ctrl+I — wraps the selection in `''`. */
class WtToggleItalicAction : WtToggleQuoteAction(WtQuoteStyle.ITALIC)
