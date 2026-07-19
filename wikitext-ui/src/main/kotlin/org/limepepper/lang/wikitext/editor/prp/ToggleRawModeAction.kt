package org.limepepper.lang.wikitext.editor.prp

import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.ToggleAction

/** Flips [PrpFormTextEditor] between the three-field form and the raw buffer. */
class ToggleRawModeAction(
    private val editor: PrpTextEditor,
) : ToggleAction(
    "Edit Raw Page Text",
    "Edit the serialized <noinclude> form directly instead of the header/body/footer fields",
    AllIcons.Actions.ToggleVisibility,
) {
    override fun isSelected(event: AnActionEvent): Boolean = editor.rawMode

    override fun setSelected(event: AnActionEvent, state: Boolean) {
        editor.rawMode = state
    }

    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.EDT
}
