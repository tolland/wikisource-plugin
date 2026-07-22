package org.limepepper.lang.wikitext.editor.prp

import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.util.Key

/**
 * Captures the editor's current selection (or the caret, for an insertion
 * point) as a new persistable [TextRange] and hands it to the page's
 * [WtTextRangeManager]. Bound in the editor popup and to a shortcut (see
 * `wikisource.wikitext-ui.xml`); enabled only in a proofread-page body editor
 * that has a manager attached.
 *
 * The manager publishes itself on its editor under [EDITOR_KEY] so the action
 * — which only has the platform [Editor] from the action event — can find it
 * without any static wiring.
 */
class CreateTextRangeAction : AnAction() {
    override fun update(event: AnActionEvent) {
        val manager = managerFor(event)
        event.presentation.isVisible = manager != null
        event.presentation.isEnabled = manager?.canCreateFromSelection() == true
    }

    override fun actionPerformed(event: AnActionEvent) {
        managerFor(event)?.createFromSelection()
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT

    private fun managerFor(event: AnActionEvent): WtTextRangeManager? =
        event.getData(CommonDataKeys.EDITOR)?.getUserData(EDITOR_KEY)

    companion object {
        /** Set by [WtTextRangeManager] on the body editor it manages. */
        val EDITOR_KEY: Key<WtTextRangeManager> = Key.create("wikitext.textRangeManager")
    }
}
