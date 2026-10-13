package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.actionSystem.DataContext
import com.intellij.openapi.editor.Caret
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.editor.actionSystem.EditorActionHandler
import com.intellij.openapi.util.Key
import com.intellij.openapi.util.TextRange

/**
 * Select All for the proofread-page editor: the first press selects only the
 * editable body (everything between the guarded header and footer tags), so
 * select-all → delete / paste works without tripping the guards. A second
 * press — selection already equals the body — falls through to the platform
 * handler and selects the whole buffer.
 *
 * The body range is published by [PrpTextEditor] on its editor under
 * [BODY_RANGE]; editors without it (plain wikitext, unstructured buffers, an
 * empty body) get the stock behaviour.
 */
class PrpSelectAllHandler(
    private val original: EditorActionHandler,
) : EditorActionHandler() {

    override fun isEnabledForCaret(editor: Editor, caret: Caret, dataContext: DataContext?): Boolean =
        original.isEnabled(editor, caret, dataContext)

    override fun doExecute(editor: Editor, caret: Caret?, dataContext: DataContext?) {
        val body = editor.getUserData(BODY_RANGE)
        val selection = editor.selectionModel
        val alreadyBody = selection.selectionStart == body?.startOffset &&
            selection.selectionEnd == body.endOffset
        if (body == null || body.isEmpty || alreadyBody) {
            original.execute(editor, caret, dataContext)
            return
        }
        editor.caretModel.removeSecondaryCarets()
        selection.setSelection(body.startOffset, body.endOffset)
    }

    companion object {
        /** Editable body span in the whole-buffer document, or absent when the buffer has no guarded frame. */
        val BODY_RANGE: Key<TextRange> = Key.create("wikitext.prp.bodyRange")
    }
}
