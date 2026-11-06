// This is a generated file. Not intended for manual editing.
package org.limepepper.lang.wikitext.psi;

import java.util.List;
import org.jetbrains.annotations.*;
import com.intellij.psi.PsiElement;
import com.intellij.psi.NavigatablePsiElement;

public interface WtTable extends NavigatablePsiElement {

  @NotNull
  List<WtComment> getCommentList();

  @NotNull
  List<WtHeading> getHeadingList();

  @NotNull
  List<WtHtmlTag> getHtmlTagList();

  @NotNull
  List<WtInternalLink> getInternalLinkList();

  @NotNull
  List<WtListItem> getListItemList();

  @NotNull
  List<WtTable> getTableList();

  @NotNull
  List<WtTemplate> getTemplateList();

  @NotNull
  List<WtVerbatimTag> getVerbatimTagList();

}
