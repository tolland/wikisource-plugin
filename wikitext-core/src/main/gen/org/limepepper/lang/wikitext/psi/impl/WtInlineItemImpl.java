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

public class WtInlineItemImpl extends ASTWrapperPsiElement implements WtInlineItem {

  public WtInlineItemImpl(@NotNull ASTNode node) {
    super(node);
  }

  public void accept(@NotNull WtVisitor visitor) {
    visitor.visitInlineItem(this);
  }

  @Override
  public void accept(@NotNull PsiElementVisitor visitor) {
    if (visitor instanceof WtVisitor) accept((WtVisitor)visitor);
    else super.accept(visitor);
  }

  @Override
  @Nullable
  public WtHtmlTag getHtmlTag() {
    return findChildByClass(WtHtmlTag.class);
  }

  @Override
  @Nullable
  public WtInternalLink getInternalLink() {
    return findChildByClass(WtInternalLink.class);
  }

  @Override
  @Nullable
  public WtTemplate getTemplate() {
    return findChildByClass(WtTemplate.class);
  }

  @Override
  @Nullable
  public WtVerbatimTag getVerbatimTag() {
    return findChildByClass(WtVerbatimTag.class);
  }

  @Override
  @Nullable
  public PsiElement getLinkDisplayText() {
    return findChildByType(LINK_DISPLAY_TEXT);
  }

  @Override
  @Nullable
  public PsiElement getPlainText() {
    return findChildByType(PLAIN_TEXT);
  }

}
