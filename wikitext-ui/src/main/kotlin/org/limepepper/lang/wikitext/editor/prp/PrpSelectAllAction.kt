package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.IdeActions
import com.intellij.openapi.actionSystem.ex.ActionUtil
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.keymap.KeymapUtil
import com.intellij.openapi.project.DumbAwareAction
import com.intellij.openapi.util.Disposer
import com.intellij.openapi.util.Key
import com.intellij.openapi.util.TextRange

/**
 * Select All for the proofread-page editor: the first press selects only the
 * editable body (everything between the guarded header and footer tags), so
 * select-all → delete / paste works without tripping the guards. A second
 * press — selection already equals the body — runs the platform's Select All
 * and selects the whole buffer.
 *
 * Installed on the editor's content component with the keymap's `$SelectAll`
 * shortcuts rather than as an `editorActionHandler` override: the component
 * action is found before the global one however the platform implements
 * Select All, so it doesn't depend on that action being an `EditorAction`.
 * The body range is published by [PrpTextEditor] under [BODY_RANGE]; with no
 * range (unstructured buffer, empty body) this just runs the platform action.
 */
class PrpSelectAllAction(
    private val editor: Editor,
) : DumbAwareAction() {

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT

    override fun actionPerformed(e: AnActionEvent) {
        val body = editor.getUserData(BODY_RANGE)
        val selection = editor.selectionModel
        val alreadyBody = selection.selectionStart == body?.startOffset &&
            selection.selectionEnd == body.endOffset
        if (body == null || body.isEmpty || alreadyBody) {
            ActionManager.getInstance().getAction(IdeActions.ACTION_SELECT_ALL)
                ?.let { ActionUtil.performActionDumbAwareWithCallbacks(it, e) }
            return
        }
        editor.caretModel.removeSecondaryCarets()
        selection.setSelection(body.startOffset, body.endOffset)
    }

    companion object {
        /** Editable body span in the whole-buffer document, or absent when the buffer has no guarded frame. */
        val BODY_RANGE: Key<TextRange> = Key.create("wikitext.prp.bodyRange")

        fun install(editor: Editor, parent: com.intellij.openapi.Disposable) {
            PrpSelectAllAction(editor).registerCustomShortcutSet(
                KeymapUtil.getActiveKeymapShortcuts(IdeActions.ACTION_SELECT_ALL),
                editor.contentComponent,
                parent,
            )
        }
    }
}
