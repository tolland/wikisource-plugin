package org.limepepper.lang.wikitext.inlay

import com.intellij.openapi.editor.event.EditorFactoryEvent
import com.intellij.openapi.editor.event.EditorFactoryListener

class ProofreadEditorListener : EditorFactoryListener {
    override fun editorCreated(event: EditorFactoryEvent) {
        //CodeEditedDocumentListener.startListening(event.editor.document)
        println("got here")
    }

    override fun editorReleased(event: EditorFactoryEvent) {
        //CodeEditedDocumentListener.stopListening(event.editor.document)
        println("got here")
    }
}
