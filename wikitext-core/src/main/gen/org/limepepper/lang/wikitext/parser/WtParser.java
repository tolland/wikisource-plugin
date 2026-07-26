// This is a generated file. Not intended for manual editing.
package org.limepepper.lang.wikitext.parser;

import com.intellij.lang.PsiBuilder;
import com.intellij.lang.PsiBuilder.Marker;
import static org.limepepper.lang.wikitext.psi.WtTypes.*;
import static org.limepepper.lang.wikitext.parser.WtParserUtil.*;
import com.intellij.psi.tree.IElementType;
import com.intellij.lang.ASTNode;
import com.intellij.psi.tree.TokenSet;
import com.intellij.lang.PsiParser;
import com.intellij.lang.LightPsiParser;

@SuppressWarnings({"SimplifiableIfStatement", "UnusedAssignment"})
public class WtParser implements PsiParser, LightPsiParser {

  public ASTNode parse(IElementType t, PsiBuilder b) {
    parseLight(t, b);
    return b.getTreeBuilt();
  }

  public void parseLight(IElementType t, PsiBuilder b) {
    boolean r;
    b = adapt_builder_(t, b, this, null);
    Marker m = enter_section_(b, 0, _COLLAPSE_, null);
    r = parse_root_(t, b);
    exit_section_(b, 0, m, t, r, true, TRUE_CONDITION);
  }

  protected boolean parse_root_(IElementType t, PsiBuilder b) {
    return parse_root_(t, b, 0);
  }

  static boolean parse_root_(IElementType t, PsiBuilder b, int l) {
    return wikitextFile(b, l + 1);
  }

  /* ********************************************************** */
  // COMMENT_START comment_run* COMMENT_END
  public static boolean comment(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "comment")) return false;
    if (!nextTokenIs(b, COMMENT_START)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, COMMENT, null);
    r = consumeToken(b, COMMENT_START);
    p = r; // pin = 1
    r = r && report_error_(b, comment_1(b, l + 1));
    r = p && consumeToken(b, COMMENT_END) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // comment_run*
  private static boolean comment_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "comment_1")) return false;
    while (true) {
      int c = current_position_(b);
      if (!comment_run(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "comment_1", c)) break;
    }
    return true;
  }

  /* ********************************************************** */
  // COMMENT_CONTENT
  static boolean comment_run(PsiBuilder b, int l) {
    return consumeToken(b, COMMENT_CONTENT);
  }

  /* ********************************************************** */
  // content_element*
  public static boolean contained_element(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "contained_element")) return false;
    Marker m = enter_section_(b, l, _NONE_, CONTAINED_ELEMENT, "<contained element>");
    while (true) {
      int c = current_position_(b);
      if (!content_element(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "contained_element", c)) break;
    }
    exit_section_(b, l, m, true, false, null);
    return true;
  }

  /* ********************************************************** */
  // internal_link
  //               | heading
  //               | list_item
  //               | table
  //               | html_tag
  //               | verbatim_tag
  //               | comment
  //               | template
  //               | PLAIN_TEXT
  //               | LINK_DISPLAY_TEXT
  //               | CHAR_ENTITY_REF
  //               | ENTITY_REF
  //               | PRE_START
  //               | NEWLINE
  static boolean content_element(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "content_element")) return false;
    boolean r;
    r = internal_link(b, l + 1);
    if (!r) r = heading(b, l + 1);
    if (!r) r = list_item(b, l + 1);
    if (!r) r = table(b, l + 1);
    if (!r) r = html_tag(b, l + 1);
    if (!r) r = verbatim_tag(b, l + 1);
    if (!r) r = comment(b, l + 1);
    if (!r) r = template(b, l + 1);
    if (!r) r = consumeToken(b, PLAIN_TEXT);
    if (!r) r = consumeToken(b, LINK_DISPLAY_TEXT);
    if (!r) r = consumeToken(b, CHAR_ENTITY_REF);
    if (!r) r = consumeToken(b, ENTITY_REF);
    if (!r) r = consumeToken(b, PRE_START);
    if (!r) r = consumeToken(b, NEWLINE);
    return r;
  }

  /* ********************************************************** */
  // H_START contained_element H_END
  public static boolean heading(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading")) return false;
    if (!nextTokenIs(b, H_START)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, HEADING, null);
    r = consumeToken(b, H_START);
    p = r; // pin = 1
    r = r && report_error_(b, contained_element(b, l + 1));
    r = p && consumeToken(b, H_END) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  /* ********************************************************** */
  // HTML_TAG_SELFCLOSE
  //            | HTML_TAG_OPEN html_tag_content HTML_TAG_CLOSE
  public static boolean html_tag(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "html_tag")) return false;
    if (!nextTokenIs(b, "<html tag>", HTML_TAG_OPEN, HTML_TAG_SELFCLOSE)) return false;
    boolean r;
    Marker m = enter_section_(b, l, _NONE_, HTML_TAG, "<html tag>");
    r = consumeToken(b, HTML_TAG_SELFCLOSE);
    if (!r) r = html_tag_1(b, l + 1);
    exit_section_(b, l, m, r, false, null);
    return r;
  }

  // HTML_TAG_OPEN html_tag_content HTML_TAG_CLOSE
  private static boolean html_tag_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "html_tag_1")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeToken(b, HTML_TAG_OPEN);
    r = r && html_tag_content(b, l + 1);
    r = r && consumeToken(b, HTML_TAG_CLOSE);
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // content_element*
  static boolean html_tag_content(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "html_tag_content")) return false;
    while (true) {
      int c = current_position_(b);
      if (!content_element(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "html_tag_content", c)) break;
    }
    return true;
  }

  /* ********************************************************** */
  // LINK_OPEN LINK_TARGET (LINK_PIPE link_display)? LINK_CLOSE
  public static boolean internal_link(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "internal_link")) return false;
    if (!nextTokenIs(b, LINK_OPEN)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, INTERNAL_LINK, null);
    r = consumeTokens(b, 1, LINK_OPEN, LINK_TARGET);
    p = r; // pin = 1
    r = r && report_error_(b, internal_link_2(b, l + 1));
    r = p && consumeToken(b, LINK_CLOSE) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // (LINK_PIPE link_display)?
  private static boolean internal_link_2(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "internal_link_2")) return false;
    internal_link_2_0(b, l + 1);
    return true;
  }

  // LINK_PIPE link_display
  private static boolean internal_link_2_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "internal_link_2_0")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeToken(b, LINK_PIPE);
    r = r && link_display(b, l + 1);
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // (content_element | LINK_PIPE)*
  static boolean link_display(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "link_display")) return false;
    while (true) {
      int c = current_position_(b);
      if (!link_display_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "link_display", c)) break;
    }
    return true;
  }

  // content_element | LINK_PIPE
  private static boolean link_display_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "link_display_0")) return false;
    boolean r;
    r = content_element(b, l + 1);
    if (!r) r = consumeToken(b, LINK_PIPE);
    return r;
  }

  /* ********************************************************** */
  // (BULLET | NUMBERED | INDENT | DEF_TERM)+ content_element*
  public static boolean list_item(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "list_item")) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _COLLAPSE_, LIST_ITEM, "<list item>");
    r = list_item_0(b, l + 1);
    p = r; // pin = 1
    r = r && list_item_1(b, l + 1);
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // (BULLET | NUMBERED | INDENT | DEF_TERM)+
  private static boolean list_item_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "list_item_0")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = list_item_0_0(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!list_item_0_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "list_item_0", c)) break;
    }
    exit_section_(b, m, null, r);
    return r;
  }

  // BULLET | NUMBERED | INDENT | DEF_TERM
  private static boolean list_item_0_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "list_item_0_0")) return false;
    boolean r;
    r = consumeToken(b, BULLET);
    if (!r) r = consumeToken(b, NUMBERED);
    if (!r) r = consumeToken(b, INDENT);
    if (!r) r = consumeToken(b, DEF_TERM);
    return r;
  }

  // content_element*
  private static boolean list_item_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "list_item_1")) return false;
    while (true) {
      int c = current_position_(b);
      if (!content_element(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "list_item_1", c)) break;
    }
    return true;
  }

  /* ********************************************************** */
  // TABLE_OPEN [ table_cell_content ] table_cell* TABLE_CLOSE
  public static boolean table(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "table")) return false;
    if (!nextTokenIs(b, TABLE_OPEN)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, TABLE, null);
    r = consumeToken(b, TABLE_OPEN);
    p = r; // pin = 1
    r = r && report_error_(b, table_1(b, l + 1));
    r = p && report_error_(b, table_2(b, l + 1)) && r;
    r = p && consumeToken(b, TABLE_CLOSE) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // [ table_cell_content ]
  private static boolean table_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "table_1")) return false;
    table_cell_content(b, l + 1);
    return true;
  }

  // table_cell*
  private static boolean table_2(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "table_2")) return false;
    while (true) {
      int c = current_position_(b);
      if (!table_cell(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "table_2", c)) break;
    }
    return true;
  }

  /* ********************************************************** */
  // TABLE_CELL_SEP table_cell_content
  static boolean table_cell(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "table_cell")) return false;
    if (!nextTokenIs(b, TABLE_CELL_SEP)) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeToken(b, TABLE_CELL_SEP);
    r = r && table_cell_content(b, l + 1);
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // (content_element | TABLE_CELL_TEXT)*
  static boolean table_cell_content(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "table_cell_content")) return false;
    while (true) {
      int c = current_position_(b);
      if (!table_cell_content_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "table_cell_content", c)) break;
    }
    return true;
  }

  // content_element | TABLE_CELL_TEXT
  private static boolean table_cell_content_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "table_cell_content_0")) return false;
    boolean r;
    r = content_element(b, l + 1);
    if (!r) r = consumeToken(b, TABLE_CELL_TEXT);
    return r;
  }

  /* ********************************************************** */
  // TEMPLATE_OPEN TEMPLATE_NAME (TEMPLATE_PIPE template_param)* TEMPLATE_CLOSE
  public static boolean template(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template")) return false;
    if (!nextTokenIs(b, TEMPLATE_OPEN)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, TEMPLATE, null);
    r = consumeTokens(b, 1, TEMPLATE_OPEN, TEMPLATE_NAME);
    p = r; // pin = 1
    r = r && report_error_(b, template_2(b, l + 1));
    r = p && consumeToken(b, TEMPLATE_CLOSE) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // (TEMPLATE_PIPE template_param)*
  private static boolean template_2(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_2")) return false;
    while (true) {
      int c = current_position_(b);
      if (!template_2_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "template_2", c)) break;
    }
    return true;
  }

  // TEMPLATE_PIPE template_param
  private static boolean template_2_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_2_0")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeToken(b, TEMPLATE_PIPE);
    r = r && template_param(b, l + 1);
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // [ TEMPLATE_PARAM_TEXT TEMPLATE_EQUALS ] template_param_value
  static boolean template_param(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_param")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = template_param_0(b, l + 1);
    r = r && template_param_value(b, l + 1);
    exit_section_(b, m, null, r);
    return r;
  }

  // [ TEMPLATE_PARAM_TEXT TEMPLATE_EQUALS ]
  private static boolean template_param_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_param_0")) return false;
    parseTokens(b, 0, TEMPLATE_PARAM_TEXT, TEMPLATE_EQUALS);
    return true;
  }

  /* ********************************************************** */
  // (content_element | TEMPLATE_PARAM_TEXT)*
  static boolean template_param_value(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_param_value")) return false;
    while (true) {
      int c = current_position_(b);
      if (!template_param_value_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "template_param_value", c)) break;
    }
    return true;
  }

  // content_element | TEMPLATE_PARAM_TEXT
  private static boolean template_param_value_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_param_value_0")) return false;
    boolean r;
    r = content_element(b, l + 1);
    if (!r) r = consumeToken(b, TEMPLATE_PARAM_TEXT);
    return r;
  }

  /* ********************************************************** */
  // VERBATIM_CONTENT
  public static boolean verbatim_body(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "verbatim_body")) return false;
    if (!nextTokenIs(b, VERBATIM_CONTENT)) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeToken(b, VERBATIM_CONTENT);
    exit_section_(b, m, VERBATIM_BODY, r);
    return r;
  }

  /* ********************************************************** */
  // HTML_TAG_OPEN verbatim_body? HTML_TAG_CLOSE
  public static boolean verbatim_tag(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "verbatim_tag")) return false;
    if (!nextTokenIs(b, HTML_TAG_OPEN)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, VERBATIM_TAG, null);
    r = consumeToken(b, HTML_TAG_OPEN);
    p = r; // pin = 1
    r = r && report_error_(b, verbatim_tag_1(b, l + 1));
    r = p && consumeToken(b, HTML_TAG_CLOSE) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // verbatim_body?
  private static boolean verbatim_tag_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "verbatim_tag_1")) return false;
    verbatim_body(b, l + 1);
    return true;
  }

  /* ********************************************************** */
  // content_element*
  static boolean wikitextFile(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "wikitextFile")) return false;
    while (true) {
      int c = current_position_(b);
      if (!content_element(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "wikitextFile", c)) break;
    }
    return true;
  }

}
