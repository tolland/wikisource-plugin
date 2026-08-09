package org.limepepper.lang.wikitext.preview

import com.intellij.openapi.fileEditor.TextEditorWithPreview
import org.limepepper.lang.wikitext.editing.WtEditingFlags

/**
 * Applies this plugin's preferred split-editor defaults to a
 * [TextEditorWithPreview].
 *
 * Two separate settings, with different persistence, hence one place that
 * knows about both:
 *
 * - **Which panes are shown** (editor / preview / both) is a constructor
 *   argument that the platform then persists per editor *name*
 *   (`PropertiesComponent`), so it is a genuine default: a user who switches
 *   to preview-only keeps that. Both wikitext editors already ask for
 *   `SHOW_EDITOR_AND_PREVIEW` — you generally want to see the source and the
 *   render together.
 * - **The split orientation** is *not* persisted at all —
 *   `setVerticalSplit` only updates the field and the splitter. So this has to
 *   be re-applied on every open, and a user's toolbar change lasts only for
 *   that editor's lifetime.
 *
 * Stacked (editor above preview) rather than side by side because wikitext
 * lines are long: splitting the width leaves both panes too narrow to read,
 * while splitting the height costs only lines of context.
 *
 * Must be called *after* the editor's lazy UI exists, since setting the
 * orientation reaches into the splitter.
 */
object WtPreviewLayoutDefaults {

    fun apply(editor: TextEditorWithPreview) {
        if (WtEditingFlags.previewVerticalSplit()) {
            // Called, not assigned: the platform backs this with a private
            // property plus public accessor methods, so there is no Kotlin
            // property to set.
            editor.setVerticalSplit(true)
        }
    }
}
