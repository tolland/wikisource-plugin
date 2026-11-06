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

public class WtInternalLinkImpl extends ASTWrapperPsiElement implements WtInternalLink {

  public WtInternalLinkImpl(@NotNull ASTNode node) {
    super(node);
  }

  public void accept(@NotNull WtVisitor visitor) {
    visitor.visitInternalLink(this);
  }

  @Override
  public void accept(@NotNull PsiElementVisitor visitor) {
    if (visitor instanceof WtVisitor) accept((WtVisitor)visitor);
    else super.accept(visitor);
  }

  @Override
  @NotNull
  public List<WtComment> getCommentList() {
    return PsiTreeUtil.getChildrenOfTypeAsList(this, WtComment.class);
  }

  @Override
  @NotNull
  public List<WtHeading> getHeadingList() {
    return PsiTreeUtil.getChildrenOfTypeAsList(this, WtHeading.class);
  }

  @Override
  @NotNull
  public List<WtHtmlTag> getHtmlTagList() {
    return PsiTreeUtil.getChildrenOfTypeAsList(this, WtHtmlTag.class);
  }

  @Override
  @NotNull
  public List<WtInternalLink> getInternalLinkList() {
    return PsiTreeUtil.getChildrenOfTypeAsList(this, WtInternalLink.class);
  }

  @Override
  @NotNull
  public List<WtListItem> getListItemList() {
    return PsiTreeUtil.getChildrenOfTypeAsList(this, WtListItem.class);
  }

  @Override
  @NotNull
  public List<WtTable> getTableList() {
    return PsiTreeUtil.getChildrenOfTypeAsList(this, WtTable.class);
  }

  @Override
  @NotNull
  public List<WtTemplate> getTemplateList() {
    return PsiTreeUtil.getChildrenOfTypeAsList(this, WtTemplate.class);
  }

  @Override
  @NotNull
  public List<WtVerbatimTag> getVerbatimTagList() {
    return PsiTreeUtil.getChildrenOfTypeAsList(this, WtVerbatimTag.class);
  }

  @Override
  @Nullable
  public PsiElement getLinkTarget() {
    return findChildByType(LINK_TARGET);
  }

}
