// This is a generated file. Not intended for manual editing.
package org.limepepper.lang.wikitext.psi;

import java.util.List;
import org.jetbrains.annotations.*;
import com.intellij.psi.PsiElement;

public interface WtTemplate extends PsiElement {

  @NotNull
  List<WtTemplateParam> getTemplateParamList();

  @Nullable
  WtTemplateTitle getTemplateTitle();

}
