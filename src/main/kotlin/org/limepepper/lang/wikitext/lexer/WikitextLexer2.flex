package org.limepepper.lang.wikitext.lexer;

import com.intellij.lexer.FlexLexer;
import com.intellij.psi.tree.IElementType;

import static com.intellij.psi.TokenType.BAD_CHARACTER;
import static com.intellij.psi.TokenType.WHITE_SPACE;
import static org.limepepper.lang.wikitext.psi.WikiTypes.*;

%%

%{
  public WikitextLexer() {
    this((java.io.Reader)null);
  }
%}

%public
%class WikitextLexer
%implements FlexLexer
%function advance
%type IElementType
%unicode

%{
    private Stack<Integer> stack = new Stack<>();

    public void yypushState(int newState) {
      stack.push(yystate());
      yybegin(newState);
    }

    public void yypopState() {
      yybegin(stack.pop());
    }
%}

EOL=\R
WHITE_SPACE=\s+

FIVE_APOS='''''
THREE_APOS='''
TWO_APOS=''
SINGLE_APOS='
NEWLINE=\r?\n
SPACE=[ \t\n\x0B\f\r]+
PLAIN_TEXT=[^\s\[\]{}|=']+

%%
<YYINITIAL> {
  {WHITE_SPACE}       { return WHITE_SPACE; }

  "[["                { return LBRACK_DBL; }
  "]]"                { return RBRACK_DBL; }
  "["                 { return LBRACK; }
  "]"                 { return RBRACK; }
  "{{"                { return LBRACE_DBL; }
  "}}"                { return RBRACE_DBL; }
  "|"                 { return PIPE; }
  "="                 { return EQUALS; }
  "="                 { return H1_START; }
  "=="                { return H2_START; }
  "==="               { return H3_START; }
  "===="              { return H4_START; }
  "====="             { return H5_START; }
  "======"            { return H6_START; }
  "*"                 { return BULLET; }
  "#"                 { return NUMBER; }

  {FIVE_APOS}         { return FIVE_APOS; }
  {THREE_APOS}        { return THREE_APOS; }
  {TWO_APOS}          { return TWO_APOS; }
  {SINGLE_APOS}       { return SINGLE_APOS; }
  {NEWLINE}           { return NEWLINE; }
  {SPACE}             { return SPACE; }
  {PLAIN_TEXT}        { return PLAIN_TEXT; }

}

[^] { return BAD_CHARACTER; }
