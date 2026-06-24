// This is a generated file. Not intended for manual editing.
package org.limepepper.lang.wikitext.psi;

import com.intellij.psi.tree.IElementType;
import com.intellij.psi.PsiElement;
import com.intellij.lang.ASTNode;
import org.limepepper.lang.wikitext.psi.impl.*;

public interface WtTypes {

  IElementType BOLD = new WtElementType("BOLD");
  IElementType BOLD_ITALIC = new WtElementType("BOLD_ITALIC");
  IElementType EXTERNAL_LINK = new WtElementType("EXTERNAL_LINK");
  IElementType HEADING_1 = new WtElementType("HEADING_1");
  IElementType HEADING_2 = new WtElementType("HEADING_2");
  IElementType HEADING_3 = new WtElementType("HEADING_3");
  IElementType HEADING_4 = new WtElementType("HEADING_4");
  IElementType HEADING_5 = new WtElementType("HEADING_5");
  IElementType HEADING_6 = new WtElementType("HEADING_6");
  IElementType HEADING_LINE = new WtElementType("HEADING_LINE");
  IElementType INLINE_ITEM = new WtElementType("INLINE_ITEM");
  IElementType INTERNAL_LINK = new WtElementType("INTERNAL_LINK");
  IElementType ITALIC = new WtElementType("ITALIC");
  IElementType LINK_TARGET = new WtElementType("LINK_TARGET");
  IElementType LINK_TEXT = new WtElementType("LINK_TEXT");
  IElementType LIST_ITEM = new WtElementType("LIST_ITEM");
  IElementType PARAGRAPH = new WtElementType("PARAGRAPH");
  IElementType PARAM_NAME = new WtElementType("PARAM_NAME");
  IElementType PARAM_VALUE = new WtElementType("PARAM_VALUE");
  IElementType TEMPLATE = new WtElementType("TEMPLATE");
  IElementType TEMPLATE_PARAM = new WtElementType("TEMPLATE_PARAM");
  IElementType TEMPLATE_TITLE = new WtElementType("TEMPLATE_TITLE");
  IElementType URL = new WtElementType("URL");

  IElementType BULLET = new WtTokenType("*");
  IElementType DEF_TERM = new WtTokenType(";");
  IElementType EQUALS = new WtTokenType("EQUALS");
  IElementType FIVE_APOS = new WtTokenType("FIVE_APOS");
  IElementType H2_START = new WtTokenType("==");
  IElementType H3_START = new WtTokenType("===");
  IElementType H4_START = new WtTokenType("====");
  IElementType H5_START = new WtTokenType("=====");
  IElementType H6_START = new WtTokenType("======");
  IElementType HTML_TAG_CLOSE = new WtTokenType("HTML_TAG_CLOSE");
  IElementType HTML_TAG_OPEN = new WtTokenType("HTML_TAG_OPEN");
  IElementType HTML_TAG_SELFCLOSE = new WtTokenType("HTML_TAG_SELFCLOSE");
  IElementType INDENT = new WtTokenType(":");
  IElementType LBRACK = new WtTokenType("[");
  IElementType LINK_CLOSE = new WtTokenType("]]");
  IElementType LINK_DISPLAY_TEXT = new WtTokenType("LINK_DISPLAY_TEXT");
  IElementType LINK_OPEN = new WtTokenType("[[");
  IElementType NEWLINE = new WtTokenType("NEWLINE");
  IElementType NUMBER = new WtTokenType("#");
  IElementType OPEN_TAG_HEAD = new WtTokenType("OPEN_TAG_HEAD");
  IElementType PIPE = new WtTokenType("PIPE");
  IElementType PLAIN_TEXT = new WtTokenType("PLAIN_TEXT");
  IElementType RBRACK = new WtTokenType("]");
  IElementType SINGLE_APOS = new WtTokenType("SINGLE_APOS");
  IElementType SPACE = new WtTokenType("SPACE");
  IElementType TABLE_CELL_SEP = new WtTokenType("|");
  IElementType TABLE_CELL_TEXT = new WtTokenType("TABLE_CELL_TEXT");
  IElementType TABLE_CLOSE = new WtTokenType("|}");
  IElementType TABLE_OPEN = new WtTokenType("{|");
  IElementType TEMPLATE_CLOSE = new WtTokenType("}}");
  IElementType TEMPLATE_EQUALS = new WtTokenType("=");
  IElementType TEMPLATE_NAME = new WtTokenType("TEMPLATE_NAME");
  IElementType TEMPLATE_OPEN = new WtTokenType("{{");
  IElementType TEMPLATE_PARAM_TEXT = new WtTokenType("TEMPLATE_PARAM_TEXT");
  IElementType THREE_APOS = new WtTokenType("THREE_APOS");
  IElementType TWO_APOS = new WtTokenType("TWO_APOS");
  IElementType VERBATIM_CONTENT = new WtTokenType("VERBATIM_CONTENT");

  class Factory {
    public static PsiElement createElement(ASTNode node) {
      IElementType type = node.getElementType();
      if (type == BOLD) {
        return new WtBoldImpl(node);
      }
      else if (type == BOLD_ITALIC) {
        return new WtBoldItalicImpl(node);
      }
      else if (type == EXTERNAL_LINK) {
        return new WtExternalLinkImpl(node);
      }
      else if (type == HEADING_1) {
        return new WtHeading1Impl(node);
      }
      else if (type == HEADING_2) {
        return new WtHeading2Impl(node);
      }
      else if (type == HEADING_3) {
        return new WtHeading3Impl(node);
      }
      else if (type == HEADING_4) {
        return new WtHeading4Impl(node);
      }
      else if (type == HEADING_5) {
        return new WtHeading5Impl(node);
      }
      else if (type == HEADING_6) {
        return new WtHeading6Impl(node);
      }
      else if (type == HEADING_LINE) {
        return new WtHeadingLineImpl(node);
      }
      else if (type == INLINE_ITEM) {
        return new WtInlineItemImpl(node);
      }
      else if (type == INTERNAL_LINK) {
        return new WtInternalLinkImpl(node);
      }
      else if (type == ITALIC) {
        return new WtItalicImpl(node);
      }
      else if (type == LINK_TARGET) {
        return new WtLinkTargetImpl(node);
      }
      else if (type == LINK_TEXT) {
        return new WtLinkTextImpl(node);
      }
      else if (type == LIST_ITEM) {
        return new WtListItemImpl(node);
      }
      else if (type == PARAGRAPH) {
        return new WtParagraphImpl(node);
      }
      else if (type == PARAM_NAME) {
        return new WtParamNameImpl(node);
      }
      else if (type == PARAM_VALUE) {
        return new WtParamValueImpl(node);
      }
      else if (type == TEMPLATE) {
        return new WtTemplateImpl(node);
      }
      else if (type == TEMPLATE_PARAM) {
        return new WtTemplateParamImpl(node);
      }
      else if (type == TEMPLATE_TITLE) {
        return new WtTemplateTitleImpl(node);
      }
      else if (type == URL) {
        return new WtUrlImpl(node);
      }
      throw new AssertionError("Unknown element type: " + type);
    }
  }
}
