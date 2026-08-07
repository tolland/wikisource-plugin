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

  enum FrameKind { TEMPLATE, TEMPLATE_PARAM, LINK, LINK_PARAM, TABLE, HTML_TAG, EXT_TAG, VERBATIM, HEADING, COMMENT }

  static final class Frame {
    final int state;       // lexer state to restore on pop
    final FrameKind kind;
    final String tagName;  // non-null only for HTML_TAG / VERBATIM frames
    Frame(int state, FrameKind kind, String tagName) {
      this.state = state;
      this.kind = kind; this.tagName = tagName;
    }
  }

  private final Deque<Frame> frames = new ArrayDeque<Frame>();

  // Helper to ensure that if we push a frame while at the start of a line,
  // it safely restores to the normal mid-line state when it pops.
  private int getNormalState(int state) {
    if (state == YYINITIAL) return WIKI_TEXT;
    if (state == TEMPLATE_BOL) return TEMPLATE;
    if (state == LINK_BOL) return LINK;
    if (state == TABLE_BOL) return TABLE;
    return state;
  }

  // Helper to find the matching BOL state when an unterminated heading forces an emergency EOL pop
  private int getBolState(int normalState) {
    if (normalState == WIKI_TEXT) return YYINITIAL;
    if (normalState == TEMPLATE) return TEMPLATE_BOL;
    if (normalState == LINK) return LINK_BOL;
    if (normalState == TABLE) return TABLE_BOL;
    return normalState;
  }

  private void pushFrame(int newState, FrameKind kind) {
    frames.push(new Frame(getNormalState(yystate()), kind, null));
    yybegin(newState);
  }

  private void pushFrame(int newState, FrameKind kind, String tagName) {
    frames.push(new Frame(getNormalState(yystate()), kind, tagName));
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

  private boolean inHeadingFrame() {
    return currentKind() == FrameKind.HEADING;
  }

  // Called when EOL/EOF is hit while a HEADING frame is on top of the
  // stack -- i.e. we opened a heading with a line-start '=' run but never
  // found a matching closing '=' run immediately followed by line-end
  // before the line ran out. This is NOT "fall back to plain text" --
  // under the fail-fast design, an unterminated heading is a real error
  // the PARSER should flag (same category as a missing '}}' or '</tag>'),
  // not something the lexer silently papers over. We still pop the frame
  // so lexing can continue sanely on the next line.
  private void closeHeadingFrameUnterminated() {
    popFrame();
  }

  // ---- Apostrophe formatting runs ----------------------------------------
  // MediaWiki's quote markup is decided purely by the LENGTH of a run of
  // apostrophes (Help:Wikitext#Text_formatting): 2 = italic, 3 = bold,
  // 5 = bold+italic. Anything else is literal text.
  //
  // The tokens are named for what was SEEN (TWO_APOS/THREE_APOS/FIVE_APOS),
  // not for what it MEANS (italic/bold), and that is deliberate. A run's
  // meaning is not knowable at lexing time, because the closing run decides
  // how an opening five-run splits:
  //
  //     '''''five''  more '''   -> italic closes first: <b><i>five</i> more </b>
  //     '''''five''' more ''    -> bold closes first:   <i><b>five</b> more </i>
  //
  // Identical prefixes, opposite nesting. A lexer cannot see far enough ahead
  // to call it, and guessing would bake a wrong answer into the token stream.
  // So the lexer reports the run length as a fact and leaves the pairing to
  // the parser, which is the only layer that sees both ends.
  //
  // Odd lengths are MediaWiki's own quirks, not ours to invent:
  //   4  -> one LITERAL apostrophe followed by bold ("''''x''''" is 'x' bolded
  //         with a stray quote), so emit the literal first and re-scan the 3.
  //   6+ -> the EXCESS is literal and the trailing five are the markup.
  // Both are handled by pushing back the markup portion so the very same rule
  // re-runs on it, rather than by duplicating the length table.
  //
  // NOTE: this deliberately does NOT try to enforce MediaWiki's "formatting
  // works only within a single line" rule. EOL is already its own token, so
  // the parser can refuse to pair runs across one; encoding it here would
  // need lexer state that the parser would then have to second-guess.
  private IElementType apostropheRun() {
    int n = yylength();
    switch (n) {
      case 1: return WtTypes.SINGLE_APOS;
      case 2: return WtTypes.TWO_APOS;
      case 3: return WtTypes.THREE_APOS;
      case 5: return WtTypes.FIVE_APOS;
      case 4:
        yypushback(3);            // leave "'''" to be re-lexed as bold
        return WtTypes.SINGLE_APOS;
      default:                    // n >= 6
        yypushback(5);            // leave "'''''" to be re-lexed as bold+italic
        return n - 5 == 1 ? WtTypes.SINGLE_APOS : WtTypes.PLAIN_TEXT;
    }
  }

  private IElementType pipeTokenForContext() {
    FrameKind k = currentKind();
    if (k == FrameKind.TEMPLATE || k == FrameKind.TEMPLATE_PARAM) {
      return WtTypes.TEMPLATE_PIPE;
    }
    if (k == FrameKind.LINK || k == FrameKind.LINK_PARAM) {
      return WtTypes.LINK_PIPE;
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

H_START      = "="{1,6}

// "'" is excluded so a run of apostrophes can never be swallowed into a
// PLAIN_TEXT run -- JFlex prefers the longest match, so without this
// exclusion "''italic''" would match PLAIN_TEXT_RUN whole and the quote
// rules below would never fire. The cost is that an ordinary contraction
// ("don't") now lexes as PLAIN_TEXT + SINGLE_APOS + PLAIN_TEXT; that is
// what SINGLE_APOS is for, and the .bnf's PLAIN_TEXT regex already
// excluded "'" in anticipation of exactly this.
NOT_DELIM = [^{}\[\]<\r\n=&*#:;']
PLAIN_TEXT_RUN = {NOT_DELIM}+

// Any run of apostrophes; apostropheRun() maps the LENGTH to a token.
APOS_RUN = "'"+

// HTML/XML character entity references -- &amp; &#39; &#x27; etc. Matched
// as their own token (rather than swallowed into PLAIN_TEXT_RUN) since a
// PageReader/transclusion consumer downstream may need to know "this is
// an entity reference, decode it" rather than treat it as five literal
// characters -- same reasoning as giving TEMPLATE_NAME its own token
// instead of letting the parser reassemble it from PLAIN_TEXT runs.
// Patterned directly on IntelliJ's bundled _HtmlLexer.flex (XML_CHAR_ENTITY_REF
// / XML_ENTITY_REF_TOKEN rules) rather than re-deriving from scratch.
ENTITY_NAME       = [a-zA-Z][a-zA-Z0-9]*
CHAR_ENTITY_REF   = "&#" [0-9]+ ";" | "&#" [xX] [0-9a-fA-F]+ ";"
ENTITY_REF        = "&" {ENTITY_NAME} ";"

// HTML/XML-style comments. Unlike VERBATIM_TAGS (which match a SAME-NAME
// open/close tag pair), comments use the fixed "<!--"/"-->" delimiter and
// their content is NEVER rendered at all -- not even conditionally, unlike
// noinclude/includeonly. A "{{template}}" inside a comment must not expand
// or even tokenize as a template, so comment content is scanned as opaque
// text, same VERBATIM-style treatment as <nowiki>/<pre> but keyed off a
// fixed delimiter rather than a tag name. Pattern lifted from IntelliJ's
// bundled _XmlLexer.flex/_HtmlLexer.flex COMMENT state: "[^\\-]|(-[^\\-])"
// is the standard trick for "scan until the literal string '-->' without
// a lookahead operator" -- it advances past any char that ISN'T '-', or
// past a '-' that's immediately followed by a non-'-' char, so the ONLY
// way to stop scanning is hitting "--" followed by '>' (matched by the
// explicit "-->" rule below, tried first per JFlex's earlier-rule-wins-on-
// tie semantics within an explicitly ordered alternative set).
COMMENT_START = "<!--"
COMMENT_END   = "-->"

WS=[\ \n\r\t\f\u2028\u2029\u0085]
TAG_NAME_CHARS = [a-zA-Z][a-zA-Z0-9]*
// minimal open-tag match: <name attr="val" attr2='val' ...> (no self-close
// handling here -- self-closing e.g. <ref name="x"/> should be matched as
// a SEPARATE, more specific rule before this one; see OPEN_TAG below split
// into self-closing vs not)
OPEN_TAG_HEAD  = "<" {TAG_NAME_CHARS}
ATTR           = {WS}+ [0-9a-zA-Z:-]+ ({WS}* "=" {WS}* (\"[^\"]*\" | '[^']*' | [^ \t\n>]+))?
OPEN_TAG_SELFCLOSE = {OPEN_TAG_HEAD} {WS}* {ATTR}* {WS}* "/>"
OPEN_TAG_FULL      = {OPEN_TAG_HEAD} {ATTR}* {WS}* ">"
CLOSE_TAG          = "</" {TAG_NAME_CHARS} {WS}* ">"

%state WIKI_TEXT
%state COMMENT
%state TEMPLATE
%state TEMPLATE_NAME
%state LINK
%state LINK_TARGET
%state TABLE
%state HTML_TAG
%state VERBATIM_TAG

// Companion Beginning-of-Line States
%state TEMPLATE_BOL
%state LINK_BOL
%state TABLE_BOL

%%

// =========================================================================
// CONTEXTUAL TOLERANCE LOOKAHEADS (Executed first inside BOL environments)
// =========================================================================

<TEMPLATE_BOL> {
  // Swallows padding whitespace safely if followed by structural layout tokens
  {LINE_WS}+ / "|"   { return WHITE_SPACE; }
  {LINE_WS}+ / "}}"  { return WHITE_SPACE; }
  {LINE_WS}+ / "{{"  { return WHITE_SPACE; }
}

<LINK_BOL> {
  {LINE_WS}+ / "|"   { return WHITE_SPACE; }
  {LINE_WS}+ / "]]"  { return WHITE_SPACE; }
  {LINE_WS}+ / "[["  { return WHITE_SPACE; }
}

<TABLE_BOL> {
  // Matches spaces before any table syntax rule (|, ||, |-, |}, !) without turning into PRE_START
  {LINE_WS}+ / "|"   { return WHITE_SPACE; }
  {LINE_WS}+ / "!"   { return WHITE_SPACE; }
  {LINE_WS}+ / "{|"  { return WHITE_SPACE; }
}


// =========================================================================
// LINE-START GATES
// =========================================================================

<YYINITIAL, TEMPLATE_BOL, LINK_BOL, TABLE_BOL> {
  "{|"   { pushFrame(TABLE, FrameKind.TABLE); return WtTypes.TABLE_OPEN; }

  // Heading open marker. Optimistically commits to heading-mode lexing --
  // see the H_START macro comment above for why we no longer pre-validate
  // the whole line. Content is lexed via WIKI_TEXT (full frame-awareness:
  // templates/tags/links inside headings just work), and the close-match
  // happens in WIKI_TEXT's own '=' rule, gated on the HEADING frame being
  // on top of the stack.
  {H_START} {
    pushFrame(WIKI_TEXT, FrameKind.HEADING);
    return WtTypes.H_START;
  }

  // List marker evaluation rules take priority over raw leading space rules
  {LINE_WS}{0,3} "*"+ { yybegin(getNormalState(yystate())); return WtTypes.BULLET; }
  {LINE_WS}{0,3} "#"+ { yybegin(getNormalState(yystate())); return WtTypes.NUMBERED; }
  {LINE_WS}{0,3} ":"+ { yybegin(getNormalState(yystate())); return WtTypes.INDENT; }
  {LINE_WS}{0,3} ";"+ { yybegin(getNormalState(yystate())); return WtTypes.DEF_TERM; }

  // Detect leading space(s) that trigger preformatted rendering blocks.
  // Transitions smoothly into the normal inline body state to ensure internal markup works.
  // Note: Adjust 'WtTypes.PRE_START' to match whatever element type your implementation uses.
  {LINE_WS}+ { yybegin(getNormalState(yystate())); return WtTypes.PRE_START; }

  {EOL}  { return WtTypes.NEWLINE; } // Blank line; maintains current BOL context
}

// Fallbacks if nothing structural matched at line-start
<YYINITIAL> {
    {ANY} { yypushback(1); yybegin(WIKI_TEXT); }
}
<TEMPLATE_BOL> {
    {ANY} { yypushback(1); yybegin(TEMPLATE); }
}
<LINK_BOL> {
    {ANY} { yypushback(1); yybegin(LINK); }
}
<TABLE_BOL> {
    {ANY}       { yypushback(1); yybegin(TABLE); }
}

// =========================================================================
// WIKI_TEXT -- the body state. Everything that ISN'T line-start-gated
// syntax lives here: templates, links, HTML/extension tags, plain text,
// and the heading CLOSE-match (since heading content is lexed in this
// same state once H_START has pushed a HEADING frame).
// =========================================================================

<WIKI_TEXT> {
  "{{"   { pushFrame(TEMPLATE_NAME, FrameKind.TEMPLATE); return WtTypes.TEMPLATE_OPEN; }
  "[["   { pushFrame(LINK_TARGET, FrameKind.LINK);       return WtTypes.LINK_OPEN; }

  {COMMENT_START} { pushFrame(COMMENT, FrameKind.COMMENT); return WtTypes.COMMENT_START; }

  {OPEN_TAG_SELFCLOSE} { return handleOpenTag(true); }
  {OPEN_TAG_FULL}       { return handleOpenTag(false); }
  {CLOSE_TAG}           { return handleCloseTag(); }

  {CHAR_ENTITY_REF} { return WtTypes.CHAR_ENTITY_REF; }
  {ENTITY_REF}       { return WtTypes.ENTITY_REF; }

  // Quote markup ('' italic, ''' bold, ''''' both). Scoped to WIKI_TEXT for
  // now: TEMPLATE/LINK/TABLE have their own text char classes that still
  // absorb apostrophes, so quotes inside a table cell or link label stay
  // plain text until those states are converted too. See apostropheRun().
  {APOS_RUN} { return apostropheRun(); }

  // Heading close-match: a run of '=' immediately followed by line-end,
  // but ONLY when the HEADING frame is the one on top of the stack (i.e.
  // we're not nested inside a template/link/tag opened since the heading
  // started -- "<code>e=mc^2</code>" never offers '=' as a close
  // candidate here because while inside <code>'s frame, THAT frame is on
  // top, not HEADING, so this rule doesn't even fire for that '='; it
  // falls through to the bare-'=' rule below as ordinary text instead).
  "="+ {LINE_WS}* / {EOL} {
    if (inHeadingFrame()) {
      popFrame(); // back to YYINITIAL for the NEWLINE that follows
      return WtTypes.H_END;
    }
    return WtTypes.PLAIN_TEXT; // '=' run at EOL outside any heading -- just text
  }

  "="+ {LINE_WS}* {
    if (inHeadingFrame() && zzMarkedPos >= zzEndRead) {
      popFrame();
      return WtTypes.H_END;
    }
    return WtTypes.PLAIN_TEXT;
  }

  {EOL} {
    if (inHeadingFrame()) {
      int restoreState = frames.isEmpty() ? WIKI_TEXT : frames.peek().state;
      closeHeadingFrameUnterminated();
      yybegin(getBolState(restoreState));
    } else {
      yybegin(YYINITIAL);
    }
    return WtTypes.NEWLINE;
  }

  {PLAIN_TEXT_RUN} { return WtTypes.PLAIN_TEXT; }
  {ANY}            { return WtTypes.PLAIN_TEXT; } // single leftover delimiter char (e.g. bare '=' not followed by EOL, or stray '}'/']' with no opener)
}

// =========================================================================
// TEMPLATE Contexts
// =========================================================================

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

  {COMMENT_START} { pushFrame(COMMENT, FrameKind.COMMENT); return WtTypes.COMMENT_START; }

  {OPEN_TAG_SELFCLOSE} { return handleOpenTag(true); }
  {OPEN_TAG_FULL}       { return handleOpenTag(false); }
  {CLOSE_TAG}           { return handleCloseTag(); }

  {CHAR_ENTITY_REF} { return WtTypes.CHAR_ENTITY_REF; }
  {ENTITY_REF}       { return WtTypes.ENTITY_REF; }

  {EOL} {
    yybegin(TEMPLATE_BOL);
    return WtTypes.NEWLINE;
  }

  [^{}|=\[<\r\n]+  { return WtTypes.TEMPLATE_PARAM_TEXT; } // Added \r\n exclusion
  {ANY}            { return WtTypes.PLAIN_TEXT; }
}

// =========================================================================
// WIKILINK Contexts
// =========================================================================

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

  {COMMENT_START} { pushFrame(COMMENT, FrameKind.COMMENT); return WtTypes.COMMENT_START; }

  {OPEN_TAG_SELFCLOSE} { return handleOpenTag(true); }
  {OPEN_TAG_FULL}       { return handleOpenTag(false); }
  {CLOSE_TAG}           { return handleCloseTag(); }

  {CHAR_ENTITY_REF} { return WtTypes.CHAR_ENTITY_REF; }
  {ENTITY_REF}       { return WtTypes.ENTITY_REF; }

  {EOL} {
    yybegin(LINK_BOL);
    return WtTypes.NEWLINE;
  }

  [^\]{|<&\r\n]+    { return WtTypes.LINK_DISPLAY_TEXT; } // Added \r\n exclusion
  {ANY}             { return WtTypes.PLAIN_TEXT; }
}

// =========================================================================
// TABLE Contexts
// =========================================================================

<TABLE> {
  "{{"        { pushFrame(TEMPLATE_NAME, FrameKind.TEMPLATE); return WtTypes.TEMPLATE_OPEN; }
  "[["        { pushFrame(LINK_TARGET, FrameKind.LINK);       return WtTypes.LINK_OPEN; }
  "|}"        { popFrame(); return WtTypes.TABLE_CLOSE; }
  "|"         { return pipeTokenForContext(); }

  {COMMENT_START} { pushFrame(COMMENT, FrameKind.COMMENT); return WtTypes.COMMENT_START; }

  {OPEN_TAG_SELFCLOSE} { return handleOpenTag(true); }
  {OPEN_TAG_FULL}       { return handleOpenTag(false); }
  {CLOSE_TAG}           { return handleCloseTag(); }

  {CHAR_ENTITY_REF} { return WtTypes.CHAR_ENTITY_REF; }
  {ENTITY_REF}       { return WtTypes.ENTITY_REF; }

  {EOL} {
    yybegin(TABLE_BOL);
    return WtTypes.NEWLINE;
  }

  [^{}\[\]|<\r\n]+ { return WtTypes.TABLE_CELL_TEXT; } // Added \r\n exclusion
  {ANY}            { return WtTypes.PLAIN_TEXT; }
}

// =========================================================================
// OPAQUE Contexts (Comments / Verbatim Tags)
// =========================================================================

<COMMENT> {
  {COMMENT_END} { popFrame(); return WtTypes.COMMENT_END; }

  // Advance past any char that ISN'T '-', or past a '-' immediately
  // followed by a non-'-' char. The only way to stop is hitting "--"
  // followed by '>', matched by {COMMENT_END} above (tried first).
  [^\-]|("-"[^\-]) { return WtTypes.COMMENT_CONTENT; }

  // lone trailing '-' at EOF with no closer -- still comment content;
  // an unterminated comment falls through to {ANY} at file scope (BAD_CHARACTER)
  // only if EOF arrives with this frame still open, same fail-fast
  // treatment as other unterminated constructs in this lexer.
  "-" { return WtTypes.COMMENT_CONTENT; }
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
