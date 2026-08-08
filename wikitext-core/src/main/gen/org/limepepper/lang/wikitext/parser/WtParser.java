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

  public ASTNode parse(IElementType root_, PsiBuilder builder_) {
    parseLight(root_, builder_);
    return builder_.getTreeBuilt();
  }

  public void parseLight(IElementType root_, PsiBuilder builder_) {
    boolean result_;
    builder_ = adapt_builder_(root_, builder_, this, null);
    Marker marker_ = enter_section_(builder_, 0, _COLLAPSE_, null);
    result_ = parse_root_(root_, builder_);
    exit_section_(builder_, 0, marker_, root_, result_, true, TRUE_CONDITION);
  }

  protected boolean parse_root_(IElementType root_, PsiBuilder builder_) {
    return parse_root_(root_, builder_, 0);
  }

  static boolean parse_root_(IElementType root_, PsiBuilder builder_, int level_) {
    return wikitextFile(builder_, level_ + 1);
  }

  /* ********************************************************** */
  // COMMENT_START comment_run* COMMENT_END
  public static boolean comment(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "comment")) return false;
    if (!nextTokenIs(builder_, COMMENT_START)) return false;
    boolean result_, pinned_;
    Marker marker_ = enter_section_(builder_, level_, _NONE_, COMMENT, null);
    result_ = consumeToken(builder_, COMMENT_START);
    pinned_ = result_; // pin = 1
    result_ = result_ && report_error_(builder_, comment_1(builder_, level_ + 1));
    result_ = pinned_ && consumeToken(builder_, COMMENT_END) && result_;
    exit_section_(builder_, level_, marker_, result_, pinned_, null);
    return result_ || pinned_;
  }

  // comment_run*
  private static boolean comment_1(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "comment_1")) return false;
    while (true) {
      int pos_ = current_position_(builder_);
      if (!comment_run(builder_, level_ + 1)) break;
      if (!empty_element_parsed_guard_(builder_, "comment_1", pos_)) break;
    }
    return true;
  }

  /* ********************************************************** */
  // COMMENT_CONTENT
  static boolean comment_run(PsiBuilder builder_, int level_) {
    return consumeToken(builder_, COMMENT_CONTENT);
  }

  /* ********************************************************** */
  // content_element*
  public static boolean contained_element(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "contained_element")) return false;
    Marker marker_ = enter_section_(builder_, level_, _NONE_, CONTAINED_ELEMENT, "<contained element>");
    while (true) {
      int pos_ = current_position_(builder_);
      if (!content_element(builder_, level_ + 1)) break;
      if (!empty_element_parsed_guard_(builder_, "contained_element", pos_)) break;
    }
    exit_section_(builder_, level_, marker_, true, false, null);
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
  //               // Quote markup, accepted as inline LEAVES for now -- no
  //               // bold/italic PSI structure yet, deliberately. A run's meaning
  //               // depends on the run that closes it ("'''''x'' y'''" and
  //               // "'''''x''' y''" open identically and nest oppositely), and
  //               // unclosed runs are common and legal in real wikitext, so a
  //               // naive pairing rule would manufacture error elements all over
  //               // ordinary pages. Accepting them as text keeps the tree honest
  //               // until the pairing pass is written. SINGLE_APOS is never
  //               // markup at all -- it is the apostrophe in "don't", split out
  //               // only because the lexer must stop PLAIN_TEXT runs at quotes.
  //               | SINGLE_APOS
  //               | TWO_APOS
  //               | THREE_APOS
  //               | FIVE_APOS
  static boolean content_element(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "content_element")) return false;
    boolean result_;
    result_ = internal_link(builder_, level_ + 1);
    if (!result_) result_ = heading(builder_, level_ + 1);
    if (!result_) result_ = list_item(builder_, level_ + 1);
    if (!result_) result_ = table(builder_, level_ + 1);
    if (!result_) result_ = html_tag(builder_, level_ + 1);
    if (!result_) result_ = verbatim_tag(builder_, level_ + 1);
    if (!result_) result_ = comment(builder_, level_ + 1);
    if (!result_) result_ = template(builder_, level_ + 1);
    if (!result_) result_ = consumeToken(builder_, PLAIN_TEXT);
    if (!result_) result_ = consumeToken(builder_, LINK_DISPLAY_TEXT);
    if (!result_) result_ = consumeToken(builder_, CHAR_ENTITY_REF);
    if (!result_) result_ = consumeToken(builder_, ENTITY_REF);
    if (!result_) result_ = consumeToken(builder_, PRE_START);
    if (!result_) result_ = consumeToken(builder_, NEWLINE);
    if (!result_) result_ = consumeToken(builder_, SINGLE_APOS);
    if (!result_) result_ = consumeToken(builder_, TWO_APOS);
    if (!result_) result_ = consumeToken(builder_, THREE_APOS);
    if (!result_) result_ = consumeToken(builder_, FIVE_APOS);
    return result_;
  }

  /* ********************************************************** */
  // H_START contained_element H_END
  public static boolean heading(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "heading")) return false;
    if (!nextTokenIs(builder_, H_START)) return false;
    boolean result_, pinned_;
    Marker marker_ = enter_section_(builder_, level_, _NONE_, HEADING, null);
    result_ = consumeToken(builder_, H_START);
    pinned_ = result_; // pin = 1
    result_ = result_ && report_error_(builder_, contained_element(builder_, level_ + 1));
    result_ = pinned_ && consumeToken(builder_, H_END) && result_;
    exit_section_(builder_, level_, marker_, result_, pinned_, null);
    return result_ || pinned_;
  }

  /* ********************************************************** */
  // HTML_TAG_SELFCLOSE
  //            | HTML_TAG_OPEN html_tag_content HTML_TAG_CLOSE
  public static boolean html_tag(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "html_tag")) return false;
    if (!nextTokenIs(builder_, "<html tag>", HTML_TAG_OPEN, HTML_TAG_SELFCLOSE)) return false;
    boolean result_;
    Marker marker_ = enter_section_(builder_, level_, _NONE_, HTML_TAG, "<html tag>");
    result_ = consumeToken(builder_, HTML_TAG_SELFCLOSE);
    if (!result_) result_ = html_tag_1(builder_, level_ + 1);
    exit_section_(builder_, level_, marker_, result_, false, null);
    return result_;
  }

  // HTML_TAG_OPEN html_tag_content HTML_TAG_CLOSE
  private static boolean html_tag_1(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "html_tag_1")) return false;
    boolean result_;
    Marker marker_ = enter_section_(builder_);
    result_ = consumeToken(builder_, HTML_TAG_OPEN);
    result_ = result_ && html_tag_content(builder_, level_ + 1);
    result_ = result_ && consumeToken(builder_, HTML_TAG_CLOSE);
    exit_section_(builder_, marker_, null, result_);
    return result_;
  }

  /* ********************************************************** */
  // content_element*
  static boolean html_tag_content(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "html_tag_content")) return false;
    while (true) {
      int pos_ = current_position_(builder_);
      if (!content_element(builder_, level_ + 1)) break;
      if (!empty_element_parsed_guard_(builder_, "html_tag_content", pos_)) break;
    }
    return true;
  }

  /* ********************************************************** */
  // LINK_OPEN LINK_TARGET (LINK_PIPE link_display)? LINK_CLOSE
  public static boolean internal_link(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "internal_link")) return false;
    if (!nextTokenIs(builder_, LINK_OPEN)) return false;
    boolean result_, pinned_;
    Marker marker_ = enter_section_(builder_, level_, _NONE_, INTERNAL_LINK, null);
    result_ = consumeTokens(builder_, 1, LINK_OPEN, LINK_TARGET);
    pinned_ = result_; // pin = 1
    result_ = result_ && report_error_(builder_, internal_link_2(builder_, level_ + 1));
    result_ = pinned_ && consumeToken(builder_, LINK_CLOSE) && result_;
    exit_section_(builder_, level_, marker_, result_, pinned_, null);
    return result_ || pinned_;
  }

  // (LINK_PIPE link_display)?
  private static boolean internal_link_2(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "internal_link_2")) return false;
    internal_link_2_0(builder_, level_ + 1);
    return true;
  }

  // LINK_PIPE link_display
  private static boolean internal_link_2_0(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "internal_link_2_0")) return false;
    boolean result_;
    Marker marker_ = enter_section_(builder_);
    result_ = consumeToken(builder_, LINK_PIPE);
    result_ = result_ && link_display(builder_, level_ + 1);
    exit_section_(builder_, marker_, null, result_);
    return result_;
  }

  /* ********************************************************** */
  // (content_element | LINK_PIPE)*
  static boolean link_display(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "link_display")) return false;
    while (true) {
      int pos_ = current_position_(builder_);
      if (!link_display_0(builder_, level_ + 1)) break;
      if (!empty_element_parsed_guard_(builder_, "link_display", pos_)) break;
    }
    return true;
  }

  // content_element | LINK_PIPE
  private static boolean link_display_0(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "link_display_0")) return false;
    boolean result_;
    result_ = content_element(builder_, level_ + 1);
    if (!result_) result_ = consumeToken(builder_, LINK_PIPE);
    return result_;
  }

  /* ********************************************************** */
  // (BULLET | NUMBERED | INDENT | DEF_TERM)+ content_element*
  public static boolean list_item(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "list_item")) return false;
    boolean result_, pinned_;
    Marker marker_ = enter_section_(builder_, level_, _COLLAPSE_, LIST_ITEM, "<list item>");
    result_ = list_item_0(builder_, level_ + 1);
    pinned_ = result_; // pin = 1
    result_ = result_ && list_item_1(builder_, level_ + 1);
    exit_section_(builder_, level_, marker_, result_, pinned_, null);
    return result_ || pinned_;
  }

  // (BULLET | NUMBERED | INDENT | DEF_TERM)+
  private static boolean list_item_0(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "list_item_0")) return false;
    boolean result_;
    Marker marker_ = enter_section_(builder_);
    result_ = list_item_0_0(builder_, level_ + 1);
    while (result_) {
      int pos_ = current_position_(builder_);
      if (!list_item_0_0(builder_, level_ + 1)) break;
      if (!empty_element_parsed_guard_(builder_, "list_item_0", pos_)) break;
    }
    exit_section_(builder_, marker_, null, result_);
    return result_;
  }

  // BULLET | NUMBERED | INDENT | DEF_TERM
  private static boolean list_item_0_0(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "list_item_0_0")) return false;
    boolean result_;
    result_ = consumeToken(builder_, BULLET);
    if (!result_) result_ = consumeToken(builder_, NUMBERED);
    if (!result_) result_ = consumeToken(builder_, INDENT);
    if (!result_) result_ = consumeToken(builder_, DEF_TERM);
    return result_;
  }

  // content_element*
  private static boolean list_item_1(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "list_item_1")) return false;
    while (true) {
      int pos_ = current_position_(builder_);
      if (!content_element(builder_, level_ + 1)) break;
      if (!empty_element_parsed_guard_(builder_, "list_item_1", pos_)) break;
    }
    return true;
  }

  /* ********************************************************** */
  // TABLE_OPEN [ table_cell_content ] table_cell* TABLE_CLOSE
  public static boolean table(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "table")) return false;
    if (!nextTokenIs(builder_, TABLE_OPEN)) return false;
    boolean result_, pinned_;
    Marker marker_ = enter_section_(builder_, level_, _NONE_, TABLE, null);
    result_ = consumeToken(builder_, TABLE_OPEN);
    pinned_ = result_; // pin = 1
    result_ = result_ && report_error_(builder_, table_1(builder_, level_ + 1));
    result_ = pinned_ && report_error_(builder_, table_2(builder_, level_ + 1)) && result_;
    result_ = pinned_ && consumeToken(builder_, TABLE_CLOSE) && result_;
    exit_section_(builder_, level_, marker_, result_, pinned_, null);
    return result_ || pinned_;
  }

  // [ table_cell_content ]
  private static boolean table_1(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "table_1")) return false;
    table_cell_content(builder_, level_ + 1);
    return true;
  }

  // table_cell*
  private static boolean table_2(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "table_2")) return false;
    while (true) {
      int pos_ = current_position_(builder_);
      if (!table_cell(builder_, level_ + 1)) break;
      if (!empty_element_parsed_guard_(builder_, "table_2", pos_)) break;
    }
    return true;
  }

  /* ********************************************************** */
  // TABLE_CELL_SEP table_cell_content
  static boolean table_cell(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "table_cell")) return false;
    if (!nextTokenIs(builder_, TABLE_CELL_SEP)) return false;
    boolean result_;
    Marker marker_ = enter_section_(builder_);
    result_ = consumeToken(builder_, TABLE_CELL_SEP);
    result_ = result_ && table_cell_content(builder_, level_ + 1);
    exit_section_(builder_, marker_, null, result_);
    return result_;
  }

  /* ********************************************************** */
  // (content_element | TABLE_CELL_TEXT)*
  static boolean table_cell_content(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "table_cell_content")) return false;
    while (true) {
      int pos_ = current_position_(builder_);
      if (!table_cell_content_0(builder_, level_ + 1)) break;
      if (!empty_element_parsed_guard_(builder_, "table_cell_content", pos_)) break;
    }
    return true;
  }

  // content_element | TABLE_CELL_TEXT
  private static boolean table_cell_content_0(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "table_cell_content_0")) return false;
    boolean result_;
    result_ = content_element(builder_, level_ + 1);
    if (!result_) result_ = consumeToken(builder_, TABLE_CELL_TEXT);
    return result_;
  }

  /* ********************************************************** */
  // TEMPLATE_OPEN TEMPLATE_NAME (TEMPLATE_PIPE template_param)* TEMPLATE_CLOSE
  public static boolean template(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "template")) return false;
    if (!nextTokenIs(builder_, TEMPLATE_OPEN)) return false;
    boolean result_, pinned_;
    Marker marker_ = enter_section_(builder_, level_, _NONE_, TEMPLATE, null);
    result_ = consumeTokens(builder_, 1, TEMPLATE_OPEN, TEMPLATE_NAME);
    pinned_ = result_; // pin = 1
    result_ = result_ && report_error_(builder_, template_2(builder_, level_ + 1));
    result_ = pinned_ && consumeToken(builder_, TEMPLATE_CLOSE) && result_;
    exit_section_(builder_, level_, marker_, result_, pinned_, null);
    return result_ || pinned_;
  }

  // (TEMPLATE_PIPE template_param)*
  private static boolean template_2(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "template_2")) return false;
    while (true) {
      int pos_ = current_position_(builder_);
      if (!template_2_0(builder_, level_ + 1)) break;
      if (!empty_element_parsed_guard_(builder_, "template_2", pos_)) break;
    }
    return true;
  }

  // TEMPLATE_PIPE template_param
  private static boolean template_2_0(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "template_2_0")) return false;
    boolean result_;
    Marker marker_ = enter_section_(builder_);
    result_ = consumeToken(builder_, TEMPLATE_PIPE);
    result_ = result_ && template_param(builder_, level_ + 1);
    exit_section_(builder_, marker_, null, result_);
    return result_;
  }

  /* ********************************************************** */
  // [ TEMPLATE_PARAM_TEXT TEMPLATE_EQUALS ] template_param_value
  static boolean template_param(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "template_param")) return false;
    boolean result_;
    Marker marker_ = enter_section_(builder_);
    result_ = template_param_0(builder_, level_ + 1);
    result_ = result_ && template_param_value(builder_, level_ + 1);
    exit_section_(builder_, marker_, null, result_);
    return result_;
  }

  // [ TEMPLATE_PARAM_TEXT TEMPLATE_EQUALS ]
  private static boolean template_param_0(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "template_param_0")) return false;
    parseTokens(builder_, 0, TEMPLATE_PARAM_TEXT, TEMPLATE_EQUALS);
    return true;
  }

  /* ********************************************************** */
  // (content_element | TEMPLATE_PARAM_TEXT)*
  static boolean template_param_value(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "template_param_value")) return false;
    while (true) {
      int pos_ = current_position_(builder_);
      if (!template_param_value_0(builder_, level_ + 1)) break;
      if (!empty_element_parsed_guard_(builder_, "template_param_value", pos_)) break;
    }
    return true;
  }

  // content_element | TEMPLATE_PARAM_TEXT
  private static boolean template_param_value_0(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "template_param_value_0")) return false;
    boolean result_;
    result_ = content_element(builder_, level_ + 1);
    if (!result_) result_ = consumeToken(builder_, TEMPLATE_PARAM_TEXT);
    return result_;
  }

  /* ********************************************************** */
  // VERBATIM_CONTENT
  public static boolean verbatim_body(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "verbatim_body")) return false;
    if (!nextTokenIs(builder_, VERBATIM_CONTENT)) return false;
    boolean result_;
    Marker marker_ = enter_section_(builder_);
    result_ = consumeToken(builder_, VERBATIM_CONTENT);
    exit_section_(builder_, marker_, VERBATIM_BODY, result_);
    return result_;
  }

  /* ********************************************************** */
  // HTML_TAG_OPEN verbatim_body? HTML_TAG_CLOSE
  public static boolean verbatim_tag(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "verbatim_tag")) return false;
    if (!nextTokenIs(builder_, HTML_TAG_OPEN)) return false;
    boolean result_, pinned_;
    Marker marker_ = enter_section_(builder_, level_, _NONE_, VERBATIM_TAG, null);
    result_ = consumeToken(builder_, HTML_TAG_OPEN);
    pinned_ = result_; // pin = 1
    result_ = result_ && report_error_(builder_, verbatim_tag_1(builder_, level_ + 1));
    result_ = pinned_ && consumeToken(builder_, HTML_TAG_CLOSE) && result_;
    exit_section_(builder_, level_, marker_, result_, pinned_, null);
    return result_ || pinned_;
  }

  // verbatim_body?
  private static boolean verbatim_tag_1(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "verbatim_tag_1")) return false;
    verbatim_body(builder_, level_ + 1);
    return true;
  }

  /* ********************************************************** */
  // content_element*
  static boolean wikitextFile(PsiBuilder builder_, int level_) {
    if (!recursion_guard_(builder_, level_, "wikitextFile")) return false;
    while (true) {
      int pos_ = current_position_(builder_);
      if (!content_element(builder_, level_ + 1)) break;
      if (!empty_element_parsed_guard_(builder_, "wikitextFile", pos_)) break;
    }
    return true;
  }

}
