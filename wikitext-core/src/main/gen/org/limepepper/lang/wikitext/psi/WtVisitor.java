// This is a generated file. Not intended for manual editing.
package org.limepepper.lang.wikitext.psi;

import org.jetbrains.annotations.*;
import com.intellij.psi.PsiElementVisitor;
import com.intellij.psi.NavigatablePsiElement;

public class WtVisitor extends PsiElementVisitor {

  public void visitComment(@NotNull WtComment o) {
    visitNavigatablePsiElement(o);
  }

  public void visitHeading(@NotNull WtHeading o) {
    visitNavigatablePsiElement(o);
  }

  public void visitHtmlTag(@NotNull WtHtmlTag o) {
    visitNavigatablePsiElement(o);
  }

  public void visitInlineItem(@NotNull WtInlineItem o) {
    visitNavigatablePsiElement(o);
  }

  public void visitInternalLink(@NotNull WtInternalLink o) {
    visitNavigatablePsiElement(o);
  }

  public void visitListItem(@NotNull WtListItem o) {
    visitNavigatablePsiElement(o);
  }

  public void visitParagraph(@NotNull WtParagraph o) {
    visitNavigatablePsiElement(o);
  }

  public void visitTable(@NotNull WtTable o) {
    visitNavigatablePsiElement(o);
  }

  public void visitTemplate(@NotNull WtTemplate o) {
    visitNavigatablePsiElement(o);
  }

  public void visitVerbatimTag(@NotNull WtVerbatimTag o) {
    visitNavigatablePsiElement(o);
  }

  public void visitNavigatablePsiElement(@NotNull NavigatablePsiElement o) {
    visitElement(o);
  }

}
