// This is a generated file. Not intended for manual editing.
package org.limepepper.lang.wikitext.psi;

import com.intellij.psi.tree.IElementType;
import com.intellij.psi.PsiElement;
import com.intellij.lang.ASTNode;
import org.limepepper.lang.wikitext.psi.impl.*;

public interface WtTypes {

  IElementType HEADING = new WtElementType("HEADING");
  IElementType HTML_TAG = new WtElementType("HTML_TAG");
  IElementType INLINE_ITEM = new WtElementType("INLINE_ITEM");
  IElementType INTERNAL_LINK = new WtElementType("INTERNAL_LINK");
  IElementType LIST_ITEM = new WtElementType("LIST_ITEM");
  IElementType PARAGRAPH = new WtElementType("PARAGRAPH");
  IElementType TABLE = new WtElementType("TABLE");
  IElementType TEMPLATE = new WtElementType("TEMPLATE");
  IElementType VERBATIM_TAG = new WtElementType("VERBATIM_TAG");

  IElementType BULLET = new WtTokenType("*");
  IElementType DEF_TERM = new WtTokenType(";");
  IElementType FIVE_APOS = new WtTokenType("FIVE_APOS");
  IElementType HTML_TAG_CLOSE = new WtTokenType("HTML_TAG_CLOSE");
  IElementType HTML_TAG_CLOSE_MISMATCHED = new WtTokenType("HTML_TAG_CLOSE_MISMATCHED");
  IElementType HTML_TAG_OPEN = new WtTokenType("HTML_TAG_OPEN");
  IElementType HTML_TAG_SELFCLOSE = new WtTokenType("HTML_TAG_SELFCLOSE");
  IElementType H_END = new WtTokenType("H_END");
  IElementType H_START = new WtTokenType("H_START");
  IElementType INDENT = new WtTokenType(":");
  IElementType LBRACK = new WtTokenType("[");
  IElementType LINK_CLOSE = new WtTokenType("]]");
  IElementType LINK_DISPLAY_TEXT = new WtTokenType("LINK_DISPLAY_TEXT");
  IElementType LINK_OPEN = new WtTokenType("[[");
  IElementType LINK_PIPE = new WtTokenType("|");
  IElementType LINK_TARGET = new WtTokenType("LINK_TARGET");
  IElementType NEWLINE = new WtTokenType("NEWLINE");
  IElementType NUMBERED = new WtTokenType("#");
  IElementType OPEN_TAG_HEAD = new WtTokenType("OPEN_TAG_HEAD");
  IElementType PLAIN_TEXT = new WtTokenType("PLAIN_TEXT");
  IElementType RBRACK = new WtTokenType("]");
  IElementType SINGLE_APOS = new WtTokenType("SINGLE_APOS");
  IElementType TABLE_CELL_SEP = new WtTokenType("TABLE_CELL_SEP");
  IElementType TABLE_CELL_TEXT = new WtTokenType("TABLE_CELL_TEXT");
  IElementType TABLE_CLOSE = new WtTokenType("|}");
  IElementType TABLE_OPEN = new WtTokenType("{|");
  IElementType TEMPLATE_CLOSE = new WtTokenType("}}");
  IElementType TEMPLATE_EQUALS = new WtTokenType("=");
  IElementType TEMPLATE_NAME = new WtTokenType("TEMPLATE_NAME");
  IElementType TEMPLATE_OPEN = new WtTokenType("{{");
  IElementType TEMPLATE_PARAM_TEXT = new WtTokenType("TEMPLATE_PARAM_TEXT");
  IElementType TEMPLATE_PIPE = new WtTokenType("TEMPLATE_PIPE");
  IElementType THREE_APOS = new WtTokenType("THREE_APOS");
  IElementType TWO_APOS = new WtTokenType("TWO_APOS");
  IElementType VERBATIM_CONTENT = new WtTokenType("VERBATIM_CONTENT");

  class Factory {
    public static PsiElement createElement(ASTNode node) {
      IElementType type = node.getElementType();
      if (type == HEADING) {
        return new WtHeadingImpl(node);
      }
      else if (type == HTML_TAG) {
        return new WtHtmlTagImpl(node);
      }
      else if (type == INLINE_ITEM) {
        return new WtInlineItemImpl(node);
      }
      else if (type == INTERNAL_LINK) {
        return new WtInternalLinkImpl(node);
      }
      else if (type == LIST_ITEM) {
        return new WtListItemImpl(node);
      }
      else if (type == PARAGRAPH) {
        return new WtParagraphImpl(node);
      }
      else if (type == TABLE) {
        return new WtTableImpl(node);
      }
      else if (type == TEMPLATE) {
        return new WtTemplateImpl(node);
      }
      else if (type == VERBATIM_TAG) {
        return new WtVerbatimTagImpl(node);
      }
      throw new AssertionError("Unknown element type: " + type);
    }
  }
}
