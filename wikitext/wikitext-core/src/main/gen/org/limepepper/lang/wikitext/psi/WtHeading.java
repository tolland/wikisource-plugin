// This is a generated file. Not intended for manual editing.
package org.limepepper.lang.wikitext.psi;

import java.util.List;
import org.jetbrains.annotations.*;
import com.intellij.psi.PsiElement;
import com.intellij.psi.NavigatablePsiElement;

public interface WtHeading extends NavigatablePsiElement {

  @Nullable
  WtContainedElement getContainedElement();

  @Nullable
  PsiElement getHEnd();

  @NotNull
  PsiElement getHStart();

  int getLevel();

}
