// This is a generated file. Not intended for manual editing.
package org.limepepper.lang.wikitext.psi;

import org.jetbrains.annotations.*;
import com.intellij.psi.PsiElementVisitor;
import com.intellij.psi.NavigatablePsiElement;
import com.intellij.psi.PsiLanguageInjectionHost;

public class WtVisitor extends PsiElementVisitor {

  public void visitComment(@NotNull WtComment o) {
    visitNavigatablePsiElement(o);
  }

  public void visitContainedElement(@NotNull WtContainedElement o) {
    visitNavigatablePsiElement(o);
  }

  public void visitHeading(@NotNull WtHeading o) {
    visitNavigatablePsiElement(o);
  }

  public void visitHtmlTag(@NotNull WtHtmlTag o) {
    visitNavigatablePsiElement(o);
  }

  public void visitInternalLink(@NotNull WtInternalLink o) {
    visitNavigatablePsiElement(o);
  }

  public void visitListItem(@NotNull WtListItem o) {
    visitNavigatablePsiElement(o);
  }

  public void visitTable(@NotNull WtTable o) {
    visitNavigatablePsiElement(o);
  }

  public void visitTemplate(@NotNull WtTemplate o) {
    visitNavigatablePsiElement(o);
  }

  public void visitVerbatimBody(@NotNull WtVerbatimBody o) {
    visitPsiLanguageInjectionHost(o);
  }

  public void visitVerbatimTag(@NotNull WtVerbatimTag o) {
    visitVerbatimTagMixin(o);
  }

  public void visitPsiLanguageInjectionHost(@NotNull PsiLanguageInjectionHost o) {
    visitElement(o);
  }

  public void visitVerbatimTagMixin(@NotNull WtVerbatimTagMixin o) {
    visitNavigatablePsiElement(o);
  }

  public void visitNavigatablePsiElement(@NotNull NavigatablePsiElement o) {
    visitElement(o);
  }

}
