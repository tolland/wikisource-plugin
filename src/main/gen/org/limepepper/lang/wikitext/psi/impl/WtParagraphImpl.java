// This is a generated file. Not intended for manual editing.
package org.limepepper.lang.wikitext.psi.impl;

import java.util.List;
import org.jetbrains.annotations.*;
import com.intellij.lang.ASTNode;
import com.intellij.psi.PsiElement;
import com.intellij.psi.PsiElementVisitor;
import com.intellij.psi.util.PsiTreeUtil;
import static org.limepepper.lang.wikitext.psi.WtTypes.*;
import com.intellij.extapi.psi.ASTWrapperPsiElement;
import org.limepepper.lang.wikitext.psi.*;

public class WtParagraphImpl extends ASTWrapperPsiElement implements WtParagraph {

  public WtParagraphImpl(@NotNull ASTNode node) {
    super(node);
  }

  public void accept(@NotNull WtVisitor visitor) {
    visitor.visitParagraph(this);
  }

  @Override
  public void accept(@NotNull PsiElementVisitor visitor) {
    if (visitor instanceof WtVisitor) accept((WtVisitor)visitor);
    else super.accept(visitor);
  }

  @Override
  @NotNull
  public List<WtInlineItem> getInlineItemList() {
    return PsiTreeUtil.getChildrenOfTypeAsList(this, WtInlineItem.class);
  }

}
