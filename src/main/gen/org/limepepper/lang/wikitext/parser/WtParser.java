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
  // PLAIN_TEXT
  public static boolean URL(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "URL")) return false;
    if (!nextTokenIs(b, PLAIN_TEXT)) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeToken(b, PLAIN_TEXT);
    exit_section_(b, m, URL, r);
    return r;
  }

  /* ********************************************************** */
  // THREE_APOS inline_item+ THREE_APOS
  public static boolean bold(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "bold")) return false;
    if (!nextTokenIs(b, THREE_APOS)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, BOLD, null);
    r = consumeToken(b, THREE_APOS);
    p = r; // pin = 1
    r = r && report_error_(b, bold_1(b, l + 1));
    r = p && consumeToken(b, THREE_APOS) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // inline_item+
  private static boolean bold_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "bold_1")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = inline_item(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!inline_item(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "bold_1", c)) break;
    }
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // FIVE_APOS inline_item+ FIVE_APOS
  public static boolean bold_italic(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "bold_italic")) return false;
    if (!nextTokenIs(b, FIVE_APOS)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, BOLD_ITALIC, null);
    r = consumeToken(b, FIVE_APOS);
    p = r; // pin = 1
    r = r && report_error_(b, bold_italic_1(b, l + 1));
    r = p && consumeToken(b, FIVE_APOS) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // inline_item+
  private static boolean bold_italic_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "bold_italic_1")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = inline_item(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!inline_item(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "bold_italic_1", c)) break;
    }
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // LBRACK URL [ SPACE link_text ] RBRACK
  public static boolean external_link(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "external_link")) return false;
    if (!nextTokenIs(b, LBRACK)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, EXTERNAL_LINK, null);
    r = consumeToken(b, LBRACK);
    p = r; // pin = 1
    r = r && report_error_(b, URL(b, l + 1));
    r = p && report_error_(b, external_link_2(b, l + 1)) && r;
    r = p && consumeToken(b, RBRACK) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // [ SPACE link_text ]
  private static boolean external_link_2(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "external_link_2")) return false;
    external_link_2_0(b, l + 1);
    return true;
  }

  // SPACE link_text
  private static boolean external_link_2_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "external_link_2_0")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeToken(b, SPACE);
    r = r && link_text(b, l + 1);
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // EQUALS (inline_item | PIPE)+ EQUALS
  public static boolean heading1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading1")) return false;
    if (!nextTokenIs(b, EQUALS)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, HEADING_1, null);
    r = consumeToken(b, EQUALS);
    p = r; // pin = 1
    r = r && report_error_(b, heading1_1(b, l + 1));
    r = p && consumeToken(b, EQUALS) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // (inline_item | PIPE)+
  private static boolean heading1_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading1_1")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = heading1_1_0(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!heading1_1_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "heading1_1", c)) break;
    }
    exit_section_(b, m, null, r);
    return r;
  }

  // inline_item | PIPE
  private static boolean heading1_1_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading1_1_0")) return false;
    boolean r;
    r = inline_item(b, l + 1);
    if (!r) r = consumeToken(b, PIPE);
    return r;
  }

  /* ********************************************************** */
  // H2_START (inline_item | PIPE | EQUALS)+ H2_START
  public static boolean heading2(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading2")) return false;
    if (!nextTokenIs(b, H2_START)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, HEADING_2, null);
    r = consumeToken(b, H2_START);
    p = r; // pin = 1
    r = r && report_error_(b, heading2_1(b, l + 1));
    r = p && consumeToken(b, H2_START) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // (inline_item | PIPE | EQUALS)+
  private static boolean heading2_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading2_1")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = heading2_1_0(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!heading2_1_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "heading2_1", c)) break;
    }
    exit_section_(b, m, null, r);
    return r;
  }

  // inline_item | PIPE | EQUALS
  private static boolean heading2_1_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading2_1_0")) return false;
    boolean r;
    r = inline_item(b, l + 1);
    if (!r) r = consumeToken(b, PIPE);
    if (!r) r = consumeToken(b, EQUALS);
    return r;
  }

  /* ********************************************************** */
  // H3_START (inline_item | PIPE | EQUALS)+ H3_START
  public static boolean heading3(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading3")) return false;
    if (!nextTokenIs(b, H3_START)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, HEADING_3, null);
    r = consumeToken(b, H3_START);
    p = r; // pin = 1
    r = r && report_error_(b, heading3_1(b, l + 1));
    r = p && consumeToken(b, H3_START) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // (inline_item | PIPE | EQUALS)+
  private static boolean heading3_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading3_1")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = heading3_1_0(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!heading3_1_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "heading3_1", c)) break;
    }
    exit_section_(b, m, null, r);
    return r;
  }

  // inline_item | PIPE | EQUALS
  private static boolean heading3_1_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading3_1_0")) return false;
    boolean r;
    r = inline_item(b, l + 1);
    if (!r) r = consumeToken(b, PIPE);
    if (!r) r = consumeToken(b, EQUALS);
    return r;
  }

  /* ********************************************************** */
  // H4_START (inline_item | PIPE | EQUALS)+ H4_START
  public static boolean heading4(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading4")) return false;
    if (!nextTokenIs(b, H4_START)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, HEADING_4, null);
    r = consumeToken(b, H4_START);
    p = r; // pin = 1
    r = r && report_error_(b, heading4_1(b, l + 1));
    r = p && consumeToken(b, H4_START) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // (inline_item | PIPE | EQUALS)+
  private static boolean heading4_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading4_1")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = heading4_1_0(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!heading4_1_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "heading4_1", c)) break;
    }
    exit_section_(b, m, null, r);
    return r;
  }

  // inline_item | PIPE | EQUALS
  private static boolean heading4_1_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading4_1_0")) return false;
    boolean r;
    r = inline_item(b, l + 1);
    if (!r) r = consumeToken(b, PIPE);
    if (!r) r = consumeToken(b, EQUALS);
    return r;
  }

  /* ********************************************************** */
  // H5_START (inline_item | PIPE | EQUALS)+ H5_START
  public static boolean heading5(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading5")) return false;
    if (!nextTokenIs(b, H5_START)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, HEADING_5, null);
    r = consumeToken(b, H5_START);
    p = r; // pin = 1
    r = r && report_error_(b, heading5_1(b, l + 1));
    r = p && consumeToken(b, H5_START) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // (inline_item | PIPE | EQUALS)+
  private static boolean heading5_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading5_1")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = heading5_1_0(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!heading5_1_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "heading5_1", c)) break;
    }
    exit_section_(b, m, null, r);
    return r;
  }

  // inline_item | PIPE | EQUALS
  private static boolean heading5_1_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading5_1_0")) return false;
    boolean r;
    r = inline_item(b, l + 1);
    if (!r) r = consumeToken(b, PIPE);
    if (!r) r = consumeToken(b, EQUALS);
    return r;
  }

  /* ********************************************************** */
  // H6_START (inline_item | PIPE | EQUALS)+ H6_START
  public static boolean heading6(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading6")) return false;
    if (!nextTokenIs(b, H6_START)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, HEADING_6, null);
    r = consumeToken(b, H6_START);
    p = r; // pin = 1
    r = r && report_error_(b, heading6_1(b, l + 1));
    r = p && consumeToken(b, H6_START) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // (inline_item | PIPE | EQUALS)+
  private static boolean heading6_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading6_1")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = heading6_1_0(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!heading6_1_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "heading6_1", c)) break;
    }
    exit_section_(b, m, null, r);
    return r;
  }

  // inline_item | PIPE | EQUALS
  private static boolean heading6_1_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading6_1_0")) return false;
    boolean r;
    r = inline_item(b, l + 1);
    if (!r) r = consumeToken(b, PIPE);
    if (!r) r = consumeToken(b, EQUALS);
    return r;
  }

  /* ********************************************************** */
  // heading6 | heading5 | heading4 | heading3 | heading2 | heading1
  public static boolean heading_line(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "heading_line")) return false;
    boolean r;
    Marker m = enter_section_(b, l, _NONE_, HEADING_LINE, "<heading line>");
    r = heading6(b, l + 1);
    if (!r) r = heading5(b, l + 1);
    if (!r) r = heading4(b, l + 1);
    if (!r) r = heading3(b, l + 1);
    if (!r) r = heading2(b, l + 1);
    if (!r) r = heading1(b, l + 1);
    exit_section_(b, l, m, r, false, null);
    return r;
  }

  /* ********************************************************** */
  // bold_italic
  //               | bold
  //               | italic
  //               | internal_link
  //               | external_link
  //               | template
  //               | PLAIN_TEXT
  //               | SPACE
  //               | EQUALS
  //               | SINGLE_APOS
  public static boolean inline_item(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "inline_item")) return false;
    boolean r;
    Marker m = enter_section_(b, l, _NONE_, INLINE_ITEM, "<inline item>");
    r = bold_italic(b, l + 1);
    if (!r) r = bold(b, l + 1);
    if (!r) r = italic(b, l + 1);
    if (!r) r = internal_link(b, l + 1);
    if (!r) r = external_link(b, l + 1);
    if (!r) r = template(b, l + 1);
    if (!r) r = consumeToken(b, PLAIN_TEXT);
    if (!r) r = consumeToken(b, SPACE);
    if (!r) r = consumeToken(b, EQUALS);
    if (!r) r = consumeToken(b, SINGLE_APOS);
    exit_section_(b, l, m, r, false, null);
    return r;
  }

  /* ********************************************************** */
  // LINK_OPEN link_target [ PIPE link_text ] LINK_CLOSE
  public static boolean internal_link(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "internal_link")) return false;
    if (!nextTokenIs(b, LINK_OPEN)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, INTERNAL_LINK, null);
    r = consumeToken(b, LINK_OPEN);
    p = r; // pin = 1
    r = r && report_error_(b, link_target(b, l + 1));
    r = p && report_error_(b, internal_link_2(b, l + 1)) && r;
    r = p && consumeToken(b, LINK_CLOSE) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // [ PIPE link_text ]
  private static boolean internal_link_2(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "internal_link_2")) return false;
    internal_link_2_0(b, l + 1);
    return true;
  }

  // PIPE link_text
  private static boolean internal_link_2_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "internal_link_2_0")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeToken(b, PIPE);
    r = r && link_text(b, l + 1);
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // TWO_APOS inline_item+ TWO_APOS
  public static boolean italic(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "italic")) return false;
    if (!nextTokenIs(b, TWO_APOS)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, ITALIC, null);
    r = consumeToken(b, TWO_APOS);
    p = r; // pin = 1
    r = r && report_error_(b, italic_1(b, l + 1));
    r = p && consumeToken(b, TWO_APOS) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // inline_item+
  private static boolean italic_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "italic_1")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = inline_item(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!inline_item(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "italic_1", c)) break;
    }
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // heading_line
  //                | list_item
  //                | template
  //                | paragraph
  //                | NEWLINE
  static boolean item(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "item")) return false;
    boolean r;
    r = heading_line(b, l + 1);
    if (!r) r = list_item(b, l + 1);
    if (!r) r = template(b, l + 1);
    if (!r) r = paragraph(b, l + 1);
    if (!r) r = consumeToken(b, NEWLINE);
    return r;
  }

  /* ********************************************************** */
  // PLAIN_TEXT (SPACE PLAIN_TEXT)*
  public static boolean link_target(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "link_target")) return false;
    if (!nextTokenIs(b, PLAIN_TEXT)) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeToken(b, PLAIN_TEXT);
    r = r && link_target_1(b, l + 1);
    exit_section_(b, m, LINK_TARGET, r);
    return r;
  }

  // (SPACE PLAIN_TEXT)*
  private static boolean link_target_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "link_target_1")) return false;
    while (true) {
      int c = current_position_(b);
      if (!link_target_1_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "link_target_1", c)) break;
    }
    return true;
  }

  // SPACE PLAIN_TEXT
  private static boolean link_target_1_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "link_target_1_0")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeTokens(b, 0, SPACE, PLAIN_TEXT);
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // (inline_item | EQUALS)+
  public static boolean link_text(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "link_text")) return false;
    boolean r;
    Marker m = enter_section_(b, l, _NONE_, LINK_TEXT, "<link text>");
    r = link_text_0(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!link_text_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "link_text", c)) break;
    }
    exit_section_(b, l, m, r, false, null);
    return r;
  }

  // inline_item | EQUALS
  private static boolean link_text_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "link_text_0")) return false;
    boolean r;
    r = inline_item(b, l + 1);
    if (!r) r = consumeToken(b, EQUALS);
    return r;
  }

  /* ********************************************************** */
  // (BULLET | NUMBER)+ (inline_item | PIPE | EQUALS)+
  public static boolean list_item(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "list_item")) return false;
    if (!nextTokenIs(b, "<list item>", BULLET, NUMBER)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, LIST_ITEM, "<list item>");
    r = list_item_0(b, l + 1);
    p = r; // pin = 1
    r = r && list_item_1(b, l + 1);
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // (BULLET | NUMBER)+
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

  // BULLET | NUMBER
  private static boolean list_item_0_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "list_item_0_0")) return false;
    boolean r;
    r = consumeToken(b, BULLET);
    if (!r) r = consumeToken(b, NUMBER);
    return r;
  }

  // (inline_item | PIPE | EQUALS)+
  private static boolean list_item_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "list_item_1")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = list_item_1_0(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!list_item_1_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "list_item_1", c)) break;
    }
    exit_section_(b, m, null, r);
    return r;
  }

  // inline_item | PIPE | EQUALS
  private static boolean list_item_1_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "list_item_1_0")) return false;
    boolean r;
    r = inline_item(b, l + 1);
    if (!r) r = consumeToken(b, PIPE);
    if (!r) r = consumeToken(b, EQUALS);
    return r;
  }

  /* ********************************************************** */
  // (inline_item | PIPE)+
  public static boolean paragraph(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "paragraph")) return false;
    boolean r;
    Marker m = enter_section_(b, l, _NONE_, PARAGRAPH, "<paragraph>");
    r = paragraph_0(b, l + 1);
    while (r) {
      int c = current_position_(b);
      if (!paragraph_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "paragraph", c)) break;
    }
    exit_section_(b, l, m, r, false, null);
    return r;
  }

  // inline_item | PIPE
  private static boolean paragraph_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "paragraph_0")) return false;
    boolean r;
    r = inline_item(b, l + 1);
    if (!r) r = consumeToken(b, PIPE);
    return r;
  }

  /* ********************************************************** */
  // PLAIN_TEXT (SPACE PLAIN_TEXT)*
  public static boolean param_name(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "param_name")) return false;
    if (!nextTokenIs(b, PLAIN_TEXT)) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeToken(b, PLAIN_TEXT);
    r = r && param_name_1(b, l + 1);
    exit_section_(b, m, PARAM_NAME, r);
    return r;
  }

  // (SPACE PLAIN_TEXT)*
  private static boolean param_name_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "param_name_1")) return false;
    while (true) {
      int c = current_position_(b);
      if (!param_name_1_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "param_name_1", c)) break;
    }
    return true;
  }

  // SPACE PLAIN_TEXT
  private static boolean param_name_1_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "param_name_1_0")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeTokens(b, 0, SPACE, PLAIN_TEXT);
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // inline_item*
  public static boolean param_value(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "param_value")) return false;
    Marker m = enter_section_(b, l, _NONE_, PARAM_VALUE, "<param value>");
    while (true) {
      int c = current_position_(b);
      if (!inline_item(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "param_value", c)) break;
    }
    exit_section_(b, l, m, true, false, null);
    return true;
  }

  /* ********************************************************** */
  // TEMPLATE_OPEN template_title (PIPE template_param)* TEMPLATE_CLOSE
  public static boolean template(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template")) return false;
    if (!nextTokenIs(b, TEMPLATE_OPEN)) return false;
    boolean r, p;
    Marker m = enter_section_(b, l, _NONE_, TEMPLATE, null);
    r = consumeToken(b, TEMPLATE_OPEN);
    p = r; // pin = 1
    r = r && report_error_(b, template_title(b, l + 1));
    r = p && report_error_(b, template_2(b, l + 1)) && r;
    r = p && consumeToken(b, TEMPLATE_CLOSE) && r;
    exit_section_(b, l, m, r, p, null);
    return r || p;
  }

  // (PIPE template_param)*
  private static boolean template_2(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_2")) return false;
    while (true) {
      int c = current_position_(b);
      if (!template_2_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "template_2", c)) break;
    }
    return true;
  }

  // PIPE template_param
  private static boolean template_2_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_2_0")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeToken(b, PIPE);
    r = r && template_param(b, l + 1);
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // [ param_name EQUALS ] param_value
  public static boolean template_param(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_param")) return false;
    boolean r;
    Marker m = enter_section_(b, l, _NONE_, TEMPLATE_PARAM, "<template param>");
    r = template_param_0(b, l + 1);
    r = r && param_value(b, l + 1);
    exit_section_(b, l, m, r, false, null);
    return r;
  }

  // [ param_name EQUALS ]
  private static boolean template_param_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_param_0")) return false;
    template_param_0_0(b, l + 1);
    return true;
  }

  // param_name EQUALS
  private static boolean template_param_0_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_param_0_0")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = param_name(b, l + 1);
    r = r && consumeToken(b, EQUALS);
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // PLAIN_TEXT (SPACE PLAIN_TEXT)*
  public static boolean template_title(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_title")) return false;
    if (!nextTokenIs(b, PLAIN_TEXT)) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeToken(b, PLAIN_TEXT);
    r = r && template_title_1(b, l + 1);
    exit_section_(b, m, TEMPLATE_TITLE, r);
    return r;
  }

  // (SPACE PLAIN_TEXT)*
  private static boolean template_title_1(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_title_1")) return false;
    while (true) {
      int c = current_position_(b);
      if (!template_title_1_0(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "template_title_1", c)) break;
    }
    return true;
  }

  // SPACE PLAIN_TEXT
  private static boolean template_title_1_0(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "template_title_1_0")) return false;
    boolean r;
    Marker m = enter_section_(b);
    r = consumeTokens(b, 0, SPACE, PLAIN_TEXT);
    exit_section_(b, m, null, r);
    return r;
  }

  /* ********************************************************** */
  // item*
  static boolean wikitextFile(PsiBuilder b, int l) {
    if (!recursion_guard_(b, l, "wikitextFile")) return false;
    while (true) {
      int c = current_position_(b);
      if (!item(b, l + 1)) break;
      if (!empty_element_parsed_guard_(b, "wikitextFile", c)) break;
    }
    return true;
  }

}
