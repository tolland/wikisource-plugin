// This is a generated file. Not intended for manual editing.
package org.limepepper.lang.wikitext.psi;

import java.util.List;
import org.jetbrains.annotations.*;
import com.intellij.psi.PsiElement;
import com.intellij.psi.NavigatablePsiElement;

public interface WtHtmlTag extends NavigatablePsiElement {

  @NotNull
  List<WtInlineItem> getInlineItemList();

  @Nullable
  PsiElement getHtmlTagClose();

  @Nullable
  PsiElement getHtmlTagOpen();

  @Nullable
  PsiElement getHtmlTagSelfclose();

}
