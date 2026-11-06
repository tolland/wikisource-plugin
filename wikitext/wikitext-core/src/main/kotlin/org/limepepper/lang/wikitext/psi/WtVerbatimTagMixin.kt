package org.limepepper.lang.wikitext.psi

import com.intellij.psi.NavigatablePsiElement

interface WtVerbatimTagMixin : NavigatablePsiElement {
    val tagName: String?
}
