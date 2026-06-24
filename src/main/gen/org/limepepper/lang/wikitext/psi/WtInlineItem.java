// This is a generated file. Not intended for manual editing.
package org.limepepper.lang.wikitext.psi;

import java.util.List;
import org.jetbrains.annotations.*;
import com.intellij.psi.PsiElement;

public interface WtInlineItem extends PsiElement {

  @Nullable
  WtBold getBold();

  @Nullable
  WtBoldItalic getBoldItalic();

  @Nullable
  WtExternalLink getExternalLink();

  @Nullable
  WtInternalLink getInternalLink();

  @Nullable
  WtItalic getItalic();

  @Nullable
  WtTemplate getTemplate();

  @Nullable
  PsiElement getPlainText();

  @Nullable
  PsiElement getSingleApos();

  @Nullable
  PsiElement getSpace();

}
