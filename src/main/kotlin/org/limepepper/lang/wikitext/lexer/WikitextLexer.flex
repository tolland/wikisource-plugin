package org.limepepper.lang.wikitext.lexer;

import com.intellij.lexer.FlexLexer;
import com.intellij.psi.tree.IElementType;
import java.util.ArrayDeque;
import java.util.Deque;

import static com.intellij.psi.TokenType.BAD_CHARACTER;
import static com.intellij.psi.TokenType.WHITE_SPACE;
import org.limepepper.lang.wikitext.psi.WtTypes;

%%

%public
%class WtLexer
%implements FlexLexer
%unicode
%function advance
%type IElementType
%eof{
%eof}

%{

  public WtLexer() {
    this((java.io.Reader)null);
  }

  // ---- Frame-aware state stack -------------------------------------------
  // Unlike a plain "return address" stack (markdown.flex's stateStack,
  // handlebars.flex's yypushState/yypopState), each frame here also records
  // *which* delimiter opened it. That's what lets PIPE mean "next template
  // param" vs "next link param" vs "next table cell" depending on what's on
  // top of the stack, and lets the close-matcher know which closer it's
  // actually waiting for at the current depth.

  enum FrameKind { TEMPLATE, TEMPLATE_PARAM, LINK, LINK_PARAM, TABLE, HTML_TAG, EXT_TAG, VERBATIM }

  static final class Frame {
    final int state;       // lexer state to restore on pop
    final FrameKind kind;
    final String tagName;  // non-null only for HTML_TAG / VERBATIM frames
    Frame(int state, FrameKind kind, String tagName) {
      this.state = state; this.kind = kind; this.tagName = tagName;
    }
  }

  private final Deque<Frame> frames = new ArrayDeque<Frame>();

  private void pushFrame(int newState, FrameKind kind) {
    frames.push(new Frame(yystate(), kind, null));
    yybegin(newState);
  }

  private void pushFrame(int newState, FrameKind kind, String tagName) {
    frames.push(new Frame(yystate(), kind, tagName));
    yybegin(newState);
  }

  // Tags whose CONTENT is opaque text, not nested wikitext. The closer must
  // match the SAME tag name -- </pre> must not terminate a <syntaxhighmight>
  // frame, hence storing tagName per-frame rather than one global flag.
  private static final java.util.Set<String> VERBATIM_TAGS = new java.util.HashSet<String>(
      java.util.Arrays.asList("nowiki", "pre", "source", "syntaxhighlight", "score", "math", "templatedata"));

  static boolean isVerbatimTag(String name) {
    return VERBATIM_TAGS.contains(name.toLowerCase());
  }

  // Splits a HEADING_LINE token's text into (level, trimmed content).
  // Level = min(leadingEqualsCount, trailingEqualsCount), matching
  // MediaWiki's actual behavior (e.g. "==Foo=" renders as H1, not H2,
  // because the shorter side wins) capped at 6. Exposed as a static method
  // so the PARSER can call it when building the heading PSI node -- this
  // is a semantic/structural decision, not something the lexer's token
  // boundary needs to encode.
  static final class HeadingInfo {
    final int level;
    final String text;
    HeadingInfo(int level, String text) { this.level = level; this.text = text; }
  }

  static HeadingInfo splitHeading(CharSequence raw) {
    int len = raw.length();
    int leadStart = 0;
    while (leadStart < len && (raw.charAt(leadStart) == ' ' || raw.charAt(leadStart) == '\t')) leadStart++;
    int leadEnd = leadStart;
    while (leadEnd < len && raw.charAt(leadEnd) == '=') leadEnd++;
    int leadCount = leadEnd - leadStart;

    int trailEnd = len;
    while (trailEnd > leadEnd && (raw.charAt(trailEnd - 1) == ' ' || raw.charAt(trailEnd - 1) == '\t')) trailEnd--;
    int trailStart = trailEnd;
    while (trailStart > leadEnd && raw.charAt(trailStart - 1) == '=') trailStart--;
    int trailCount = trailEnd - trailStart;

    int level = Math.min(Math.min(leadCount, trailCount), 6);
    String text = raw.subSequence(leadEnd, trailStart).toString().trim();
    return new HeadingInfo(level, text);
  }

  // For an opening tag match like "<ref name=\"x\">" or "<ref>"
  static String extractTagName(CharSequence openTagText) {
    int i = 1; // skip '<'
    int start = i;
    while (i < openTagText.length() && Character.isLetterOrDigit(openTagText.charAt(i))) i++;
    return openTagText.subSequence(start, i).toString();
  }

  // For a closing tag match like "</ref>" -- skip "</" instead of "<"
  static String extractClosingTagName(CharSequence closeTagText) {
    int i = 2; // skip '</'
    int start = i;
    while (i < closeTagText.length() && Character.isLetterOrDigit(closeTagText.charAt(i))) i++;
    return closeTagText.subSequence(start, i).toString();
  }

  // Shared by every state that can contain inline HTML/extension tags
  // (YYINITIAL, TEMPLATE, LINK, TABLE). Keeps the dispatch logic in one
  // place instead of duplicating it per %state block.
  private IElementType handleOpenTag(boolean selfClosing) {
    String name = extractTagName(yytext());
    if (selfClosing) {
      // <ref name="x"/> -- no content, no frame pushed at all
      return WtTypes.HTML_TAG_SELFCLOSE;
    }
    if (isVerbatimTag(name)) {
      pushFrame(VERBATIM_TAG, FrameKind.VERBATIM, name);
    } else {
      // <ref>, <div>, <includeonly>, etc. -- contents are ordinary wikitext,
      // so return to the SAME lexing state, just remember the tag name so
      // the matching </tag> can be verified.
      pushFrame(yystate(), FrameKind.HTML_TAG, name);
    }
    return WtTypes.HTML_TAG_OPEN;
  }

  private IElementType handleCloseTag() {
    String name = extractClosingTagName(yytext());
    String expected = currentTagName();
    if (expected != null && expected.equalsIgnoreCase(name)) {
      popFrame();
      return WtTypes.HTML_TAG_CLOSE;
    }
    // mismatched closer (e.g. stray </div> with nothing matching open) --
    // emit as text/error token rather than corrupting the stack
    return WtTypes.HTML_TAG_CLOSE;
  }

  private void popFrame() {
    if (frames.isEmpty()) {
      yybegin(YYINITIAL); // recovery: stray closer with nothing open
      return;
    }
    yybegin(frames.pop().state);
  }

  private FrameKind currentKind() {
    return frames.isEmpty() ? null : frames.peek().kind;
  }

  private String currentTagName() {
    return frames.isEmpty() ? null : frames.peek().tagName;
  }

  // PIPE inside {{ }} vs [[ ]] vs {| |} all need different token types so
  // the parser can build the right PSI without re-inspecting context.
  private IElementType pipeTokenForContext() {
    FrameKind k = currentKind();
    if (k == FrameKind.TEMPLATE || k == FrameKind.TEMPLATE_PARAM) {
      return WtTypes.PIPE;
    }
    if (k == FrameKind.LINK || k == FrameKind.LINK_PARAM) {
      return WtTypes.PIPE;
    }
    if (k == FrameKind.TABLE) {
      return WtTypes.TABLE_CELL_SEP;
    }
    return WtTypes.PLAIN_TEXT; // bare '|' outside any construct
  }
%}

LINE_WS      = [ \t]
EOL          = \r\n | \r | \n
ANY          = [^]

// A candidate heading line: 1-6 leading '=', SOME content, 1-6 trailing '=',
// then only whitespace to end of line. We match the WHOLE line in one token
// (HEADING_LINE) rather than separately tokenizing "H2_START" etc., because
// validity (closing run of '=' must be followed by nothing but whitespace)
// can't be known until we've seen the rest of the line -- by the time you've
// scanned "=This is not H1=" you don't yet know if "because it has..." is
// coming next. Greedily emitting H1_START up front and hoping the rest works
// out is exactly the trap: "=This is not H1=because..." would wrongly start
// a heading token that then has to be un-done. One whole-line lookahead
// avoids that backtracking entirely.
//
// NOTE: JFlex does NOT support PCRE-style (?=...) lookahead. The trailing
// '/' operator only allows fixed lookahead context, not arbitrary
// alternation, so EOL-or-EOF can't go after '/'. Instead we match through
// the EOL itself and strip it off in the action with yypushback, the same
// technique markdown.flex uses in processEol() (see its WHITE_SPACE*
// ({EOL} WHITE_SPACE*)+ rule, lines 261-274) and handlebars.flex's '~'
// operator uses internally. EOF-terminated last line (no trailing
// newline) is handled by a second, EOL-less alternative.
HEADING_LINE = {LINE_WS}{0,3} "="{1,6} [^\r\n]* "="{1,6} {LINE_WS}* {EOL}
HEADING_LINE_EOF = {LINE_WS}{0,3} "="{1,6} [^\r\n]* "="{1,6} {LINE_WS}*

// Coalesces runs of "boring" text into one token instead of one PLAIN_TEXT
// per character (cf. markdown.flex's {ALPHANUM}+ run, handlebars.flex's
// !([^]*"{{"[^]*) "everything up to X" pattern). Excludes every character
// that starts a delimiter recognized in YYINITIAL: '{' '[' '<' (templates/
// links/tags), '\r' '\n' (line boundaries), and '=' '*' '#' ':' ';' (only
// MEANINGFUL at line-start, but excluding them unconditionally just means
// the run stops one char early there and a single-char PLAIN_TEXT token
// covers it when it turns out to be ordinary -- see note above on why this
// is needed for correctness, not just style).
NOT_DELIM = [^{}\[\]<\r\n=*#:;]
PLAIN_TEXT_RUN = {NOT_DELIM}+

WS           = [ \t]
TAG_NAME_CHARS = [a-zA-Z][a-zA-Z0-9]*
// minimal open-tag match: <name attr="val" attr2='val' ...> (no self-close
// handling here -- self-closing e.g. <ref name="x"/> should be matched as
// a SEPARATE, more specific rule before this one; see OPEN_TAG below split
// into self-closing vs not)
OPEN_TAG_HEAD  = "<" {TAG_NAME_CHARS}
ATTR           = {WS}+ [a-zA-Z:-]+ ({WS}* "=" {WS}* (\"[^\"]*\" | '[^']*' | [^ \t\n>]+))?
OPEN_TAG_SELFCLOSE = {OPEN_TAG_HEAD} {ATTR}* {WS}* "/>"
OPEN_TAG_FULL      = {OPEN_TAG_HEAD} {ATTR}* {WS}* ">"
CLOSE_TAG          = "</" {TAG_NAME_CHARS} {WS}* ">"
NOT_DELIM = [^{}\[\]<\r\n]
PLAIN_TEXT_RUN = {NOT_DELIM}+

%state TEMPLATE
%state TEMPLATE_NAME
%state LINK
%state LINK_TARGET
%state TABLE
%state HTML_TAG
%state VERBATIM_TAG

%%

// =========================================================================
// YYINITIAL / generic content states -- replace with your real block/inline
// split (heading, list, table-row-start detection, etc). Only the nesting
// machinery is fleshed out below.
// =========================================================================

<YYINITIAL> {
  "{{"   { pushFrame(TEMPLATE_NAME, FrameKind.TEMPLATE); return WtTypes.TEMPLATE_OPEN; }
  "[["   { pushFrame(LINK_TARGET, FrameKind.LINK);       return WtTypes.LINK_OPEN; }
  "{|"   { pushFrame(TABLE, FrameKind.TABLE);            return WtTypes.TABLE_OPEN; }

  {OPEN_TAG_SELFCLOSE} { return handleOpenTag(true); }
  {OPEN_TAG_FULL}       { return handleOpenTag(false); }
  {CLOSE_TAG}           { return handleCloseTag(); }

  // Headings are only meaningful at line start, and validity depends on the
  // WHOLE line (closing run of '=' must be followed by nothing but
  // whitespace) -- hence one whole-line token rather than separate
  // H1_START/H2_START-as-prefix tokens. If a line starts with '=' but
  // doesn't match this whole pattern (e.g. has trailing junk after the
  // closing run), neither rule below matches and the '=' falls through to
  // ordinary text -- no separate "not a heading" state needed.
  {HEADING_LINE} {
    // push the EOL back so it's tokenized on its own as NEWLINE -- keeps
    // line-boundary bookkeeping uniform for every line, heading or not.
    int eolLen = (yycharat(yylength() - 2) == '\r' && yycharat(yylength() - 1) == '\n') ? 2 : 1;
    yypushback(eolLen);
    return WtTypes.HEADING_LINE;
  }
  {HEADING_LINE_EOF} { return WtTypes.HEADING_LINE; } // last line, no trailing newline

  // List markers ARE safe as simple line-start prefix tokens (unlike '='),
  // because they have no closing delimiter to disambiguate against -- a
  // bullet just IS a bullet, nothing later in the line un-makes it.
  {LINE_WS}{0,3} "*"+ { return WtTypes.BULLET; }
  {LINE_WS}{0,3} "#"+ { return WtTypes.NUMBER; }
  {LINE_WS}{0,3} ":"+ { return WtTypes.INDENT; }
  {LINE_WS}{0,3} ";"+ { return WtTypes.DEF_TERM; }

  {EOL}  { return WtTypes.NEWLINE; }
  {PLAIN_TEXT_RUN} { return WtTypes.PLAIN_TEXT; }
  {ANY}  { return WtTypes.PLAIN_TEXT; }
}

// ---- Template: {{ name | param | key=value | {{nested}} }} -------------

<TEMPLATE_NAME> {
  // template name runs until first '|' or '}}', may itself contain a
  // nested {{...}} (e.g. {{ {{PAGENAME}} }} is invalid wikitext usually,
  // but {{ {{ns:Template}}:Foo | ... }}-style construction happens via
  // subst/parser functions) -- adjust per your actual grammar decision.
  "{{"        { pushFrame(TEMPLATE_NAME, FrameKind.TEMPLATE); return WtTypes.TEMPLATE_OPEN; }
  "}}"        { popFrame(); return WtTypes.TEMPLATE_CLOSE; }
  "|"         { yybegin(TEMPLATE); return pipeTokenForContext(); }
  [^{}|]+     { return WtTypes.TEMPLATE_NAME; }
  {ANY}       { return WtTypes.PLAIN_TEXT; } // stray brace, error recovery
}

<TEMPLATE> {
  "{{"        { pushFrame(TEMPLATE_NAME, FrameKind.TEMPLATE); return WtTypes.TEMPLATE_OPEN; }
  "[["        { pushFrame(LINK_TARGET, FrameKind.LINK);       return WtTypes.LINK_OPEN; }
  "}}"        { popFrame(); return WtTypes.TEMPLATE_CLOSE; }
  "|"         { return pipeTokenForContext(); } // next param at SAME depth
  "="         { return WtTypes.TEMPLATE_EQUALS; }

  {OPEN_TAG_SELFCLOSE} { return handleOpenTag(true); }
  {OPEN_TAG_FULL}       { return handleOpenTag(false); }
  {CLOSE_TAG}           { return handleCloseTag(); }

  [^{}|=\[<]+  { return WtTypes.TEMPLATE_PARAM_TEXT; }
  {ANY}       { return WtTypes.PLAIN_TEXT; }
}

// ---- Wikilink: [[ target | display | [[nested]] ]] ---------------------

<LINK_TARGET> {
  "]]"        { popFrame(); return WtTypes.LINK_CLOSE; }
  "|"         { yybegin(LINK); return pipeTokenForContext(); }
  [^\]|]+     { return WtTypes.LINK_TARGET; }
  {ANY}       { return WtTypes.PLAIN_TEXT; }
}

<LINK> {
  "[["        { pushFrame(LINK_TARGET, FrameKind.LINK);       return WtTypes.LINK_OPEN; }
  "{{"        { pushFrame(TEMPLATE_NAME, FrameKind.TEMPLATE); return WtTypes.TEMPLATE_OPEN; }
  "]]"        { popFrame(); return WtTypes.LINK_CLOSE; }
  "|"         { return pipeTokenForContext(); }

  {OPEN_TAG_SELFCLOSE} { return handleOpenTag(true); }
  {OPEN_TAG_FULL}       { return handleOpenTag(false); }
  {CLOSE_TAG}           { return handleCloseTag(); }

  [^\]{|<]+    { return WtTypes.LINK_DISPLAY_TEXT; }
  {ANY}       { return WtTypes.PLAIN_TEXT; }
}

// ---- Table: {| ... | cell | cell {{template}} ... |} -------------------
// NB: real MediaWiki table syntax is line-start-sensitive (|-, !, |+) --
// this only shows the brace/pipe nesting piece, not full table grammar.

<TABLE> {
  "{{"        { pushFrame(TEMPLATE_NAME, FrameKind.TEMPLATE); return WtTypes.TEMPLATE_OPEN; }
  "[["        { pushFrame(LINK_TARGET, FrameKind.LINK);       return WtTypes.LINK_OPEN; }
  "|}"        { popFrame(); return WtTypes.TABLE_CLOSE; }
  "|"         { return pipeTokenForContext(); }

  {OPEN_TAG_SELFCLOSE} { return handleOpenTag(true); }
  {OPEN_TAG_FULL}       { return handleOpenTag(false); }
  {CLOSE_TAG}           { return handleCloseTag(); }

  [^{}\[\]|<]+ { return WtTypes.TABLE_CELL_TEXT; }
  {ANY}       { return WtTypes.PLAIN_TEXT; }
}

// ---- Verbatim tags: <nowiki>, <pre>, <syntaxhighlight>, <source>, <math> --
// Same shape as handlebars.flex's `raw` state: scan forward for the ONE
// terminator we care about and emit everything before it as one content
// token. Crucially: no recursive frame is pushed for what's INSIDE -- a
// "{{" appearing inside <nowiki> is literally the three characters '{','{'
// and must NOT trigger pushFrame(TEMPLATE_NAME, ...). The only thing that
// can end this state is the closing tag matching the SAME name we opened
// with (currentTagName()), checked dynamically since this one state serves
// every verbatim tag rather than having a separate state per tag name.

<VERBATIM_TAG> {
  "</" {TAG_NAME_CHARS} {WS}* ">" {
    String name = extractClosingTagName(yytext());
    if (name.equalsIgnoreCase(currentTagName())) {
      popFrame();
      return WtTypes.HTML_TAG_CLOSE;
    }
    // not OUR closer (e.g. stray </div> inside a <pre> block) -- it's just
    // verbatim content, fall through as text and keep scanning.
    return WtTypes.VERBATIM_CONTENT;
  }

  // Greedily consume runs of text that don't start a potential closing tag,
  // so we're not emitting a separate token per character. ~"</" pattern
  // (handlebars.flex style "until next occurrence of X") works if your
  // JFlex version supports the ~ operator; otherwise use the more portable
  // form below.
  [^<]+ { return WtTypes.VERBATIM_CONTENT; }

  // lone '<' not starting our closing tag -- still verbatim content
  "<" { return WtTypes.VERBATIM_CONTENT; }
}

// ---- Fallback -------------------------------------------------------

//{ANY} { return WtTypes.PLAIN_TEXT; }
[^] { return BAD_CHARACTER; }
