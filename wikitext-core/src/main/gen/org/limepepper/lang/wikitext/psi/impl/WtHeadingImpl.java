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
import org.limepepper.lang.wikitext.parser.WtPsiImplUtil;

public class WtHeadingImpl extends ASTWrapperPsiElement implements WtHeading {

  public WtHeadingImpl(@NotNull ASTNode node) {
    super(node);
  }

  public void accept(@NotNull WtVisitor visitor) {
    visitor.visitHeading(this);
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

  @Override
  @Nullable
  public PsiElement getHEnd() {
    return findChildByType(H_END);
  }

  @Override
  @NotNull
  public PsiElement getHStart() {
    return findNotNullChildByType(H_START);
  }

  @Override
  public int getLevel() {
    return WtPsiImplUtil.getLevel(this);
  }

}
