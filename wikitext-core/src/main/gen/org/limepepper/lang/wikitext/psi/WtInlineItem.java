// This is a generated file. Not intended for manual editing.
package org.limepepper.lang.wikitext.psi;

import java.util.List;
import org.jetbrains.annotations.*;
import com.intellij.psi.PsiElement;
import com.intellij.psi.NavigatablePsiElement;

public interface WtInlineItem extends NavigatablePsiElement {

  @Nullable
  WtComment getComment();

  @Nullable
  WtHtmlTag getHtmlTag();

  @Nullable
  WtInternalLink getInternalLink();

  @Nullable
  WtTemplate getTemplate();

  @Nullable
  WtVerbatimTag getVerbatimTag();

  @Nullable
  PsiElement getCharEntityRef();

  @Nullable
  PsiElement getEntityRef();

  @Nullable
  PsiElement getLinkDisplayText();

  @Nullable
  PsiElement getPlainText();

}
