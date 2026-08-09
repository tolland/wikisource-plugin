package org.limepepper.lang.wikitext.editing.toggle

import com.intellij.openapi.actionSystem.ActionPromoter
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.DataContext
import org.limepepper.lang.wikitext.editing.WtEditingFlags

/**
 * Makes the wikitext toggle actions win the shortcuts they share with the
 * platform (Ctrl+B = Go To Declaration, Ctrl+I = Implement Methods).
 *
 * Disabling the platform action in wikitext files is *not* enough on its own.
 * When several enabled actions answer one keystroke the platform picks from
 * the candidate list, and without a promoter the choice is not one we control
 * — which is exactly how a shortcut ends up working in one editor and not
 * another. Promoting is the supported way to say "in this context, mine".
 *
 * Deliberately narrow: it only ever reorders actions this plugin owns, and
 * only when they are already in the candidate list — it can never introduce an
 * action the platform did not already consider applicable. Turning off
 * `wikitext.editing.toggle.promote` hands the keystrokes straight back, which
 * is the escape hatch if hijacking two very well-known shortcuts turns out to
 * be a bad trade.
 */
class WtEditingActionPromoter : ActionPromoter {

    override fun promote(actions: MutableList<out AnAction>, context: DataContext): MutableList<AnAction>? {
        if (!WtEditingFlags.toggleEnabled() || !WtEditingFlags.togglePromote()) return null
        val ours = actions.filterIsInstance<WtToggleQuoteAction>()
        return if (ours.isEmpty()) null else ours.toMutableList()
    }
}
