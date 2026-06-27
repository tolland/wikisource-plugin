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

// A line-start run of '=' opens a heading FRAME (FrameKind.HEADING) rather
// than being matched as one whole-line token. We deliberately do NOT
// pre-validate the whole line with a regex anymore: that approach greedily
// matched through to the FIRST '=' that happened to be followed by
// whitespace+EOL, which is wrong when an earlier '=' inside nested content
// (e.g. "<code>e=mc^2</code>") looks like a plausible closer but isn't one
// at all -- it's just inert text inside a tag, never evaluated as a
// heading-closer candidate once that tag's frame is on top of the stack.
//
// Instead: H_START commits to heading-mode lexing optimistically; content
// is lexed through the SAME frame-aware machinery as everywhere else
// (templates, links, tags all just work inside headings); and the close-
// matcher only accepts a trailing '=' run as the heading's closer when the
// HEADING frame is the one ON TOP of the stack (i.e. we're not nested
// inside some other construct) AND it's immediately followed by line-end.
// Hitting EOL/EOF while still inside a HEADING frame is reported as an
// unterminated heading -- a real error for the PARSER to flag, not a
// silent reinterpretation as plain text (see closeHeadingFrameUnterminated
// and project discussion on fail-fast semantics).
H_START = {LINE_WS}{0,3} "="{1,6}

// Coalesces runs of "boring" text into one token instead of one PLAIN_TEXT
// per character (cf. markdown.flex's {ALPHANUM}+ run, handlebars.flex's
// !([^]*"{{"[^]*) "everything up to X" pattern). Excludes every character
// that starts a delimiter recognized in the body state: '{' '[' '<'
// (templates/links/tags), '\r' '\n' (line boundaries), and '=' (heading
// closer candidate, only actually meaningful while inside a HEADING frame,
// but excluding it unconditionally just means a bare mid-text '=' becomes
// its own single-char token when it turns out not to close anything).
NOT_DELIM = [^{}\[\]<\r\n=&*#:;]
PLAIN_TEXT_RUN = {NOT_DELIM}+

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

%state WIKI_TEXT
%state COMMENT
%state TEMPLATE
%state TEMPLATE_NAME
%state LINK
%state LINK_TARGET
%state TABLE
%state HTML_TAG
%state VERBATIM_TAG

%%

// =========================================================================
// YYINITIAL -- LINE-START GATE ONLY. This state is re-entered after every
// NEWLINE (see WIKI_TEXT's {EOL} rule below) and is where the file starts.
// It recognizes ONLY the things that are syntactically meaningful at line
// start (headings, list markers, table-open) and otherwise falls straight
// through into WIKI_TEXT, which is where ordinary content -- templates,
// links, tags, plain text -- actually lives. This split is what fixes the
// earlier bug where "{|" / "==" / list markers were being recognized
// mid-paragraph: those rules simply don't exist in WIKI_TEXT at all, so
// e.g. a stray "{|" mid-sentence is just two ordinary characters there.
//
// IMPORTANT: nothing here pushes a "return to YYINITIAL" frame for the
// ordinary case -- once we fall through to WIKI_TEXT we STAY there
// (mid-paragraph, mid-template, wherever) until an actual NEWLINE is
// lexed, at which point WIKI_TEXT's {EOL} rule sends us back here. This
// mirrors markdown.flex's YYINITIAL/AFTER_LINE_START split (its
// resetState()/popState() pair) but we don't need an explicit stack for
// it because there's only ever one "body" state to return to, not a
// frame-specific one -- the REAL nesting (templates/links/tables/tags)
// is still tracked by the existing `frames` stack, completely orthogonal
// to this line-start/body distinction.
// =========================================================================

<YYINITIAL> {
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

  // List markers ARE safe as simple line-start prefix tokens (unlike '='),
  // because they have no closing delimiter to disambiguate against -- a
  // bullet just IS a bullet, nothing later in the line un-makes it.
  {LINE_WS}{0,3} "*"+ { yybegin(WIKI_TEXT); return WtTypes.BULLET; }
  {LINE_WS}{0,3} "#"+ { yybegin(WIKI_TEXT); return WtTypes.NUMBERED; }
  {LINE_WS}{0,3} ":"+ { yybegin(WIKI_TEXT); return WtTypes.INDENT; }
  {LINE_WS}{0,3} ";"+ { yybegin(WIKI_TEXT); return WtTypes.DEF_TERM; }

  {EOL}  { return WtTypes.NEWLINE; } // blank line
  {ANY}  { yypushback(1); yybegin(WIKI_TEXT); } // not a line-start construct -- fall through, re-lex same char in WIKI_TEXT
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

  {EOL} {
    if (inHeadingFrame()) {
      // Ran off the end of the line (or hit EOF via the EOF-safe EOL set)
      // while still inside a HEADING frame -- no closing '=' run was ever
      // found at this nesting depth. Fail-fast: this is reported as an
      // unterminated heading, for the PARSER to flag as an error, not
      // silently reinterpreted as a plain paragraph spanning the rest of
      // the heading's content. We still emit NEWLINE and pop back to
      // YYINITIAL so subsequent lines lex normally.
      closeHeadingFrameUnterminated();
    }
    yybegin(YYINITIAL);
    return WtTypes.NEWLINE;
  }

  {PLAIN_TEXT_RUN} { return WtTypes.PLAIN_TEXT; }
  {ANY}            { return WtTypes.PLAIN_TEXT; } // single leftover delimiter char (e.g. bare '=' not followed by EOL, or stray '}'/']' with no opener)
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

  {COMMENT_START} { pushFrame(COMMENT, FrameKind.COMMENT); return WtTypes.COMMENT_START; }

  {OPEN_TAG_SELFCLOSE} { return handleOpenTag(true); }
  {OPEN_TAG_FULL}       { return handleOpenTag(false); }
  {CLOSE_TAG}           { return handleCloseTag(); }

  {CHAR_ENTITY_REF} { return WtTypes.CHAR_ENTITY_REF; }
  {ENTITY_REF}       { return WtTypes.ENTITY_REF; }

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

  {COMMENT_START} { pushFrame(COMMENT, FrameKind.COMMENT); return WtTypes.COMMENT_START; }

  {OPEN_TAG_SELFCLOSE} { return handleOpenTag(true); }
  {OPEN_TAG_FULL}       { return handleOpenTag(false); }
  {CLOSE_TAG}           { return handleCloseTag(); }

  {CHAR_ENTITY_REF} { return WtTypes.CHAR_ENTITY_REF; }
  {ENTITY_REF}       { return WtTypes.ENTITY_REF; }

  [^\]{|<&]+    { return WtTypes.LINK_DISPLAY_TEXT; }
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

  {COMMENT_START} { pushFrame(COMMENT, FrameKind.COMMENT); return WtTypes.COMMENT_START; }

  {OPEN_TAG_SELFCLOSE} { return handleOpenTag(true); }
  {OPEN_TAG_FULL}       { return handleOpenTag(false); }
  {CLOSE_TAG}           { return handleCloseTag(); }

  {CHAR_ENTITY_REF} { return WtTypes.CHAR_ENTITY_REF; }
  {ENTITY_REF}       { return WtTypes.ENTITY_REF; }

  [^{}\[\]|<]+ { return WtTypes.TABLE_CELL_TEXT; }
  {ANY}       { return WtTypes.PLAIN_TEXT; }
}

// ---- HTML/XML-style comments: <!-- ... --> --------------------------
// Content is NEVER rendered (stricter than noinclude -- not even
// conditionally transcluded), so it's scanned as opaque text, same as a
// verbatim tag's content, but keyed off the fixed "<!--"/"-->" delimiter
// rather than a matched tag name -- see the COMMENT_START/COMMENT_END
// macro comment above for the "[^\\-]|(-[^\\-])" technique this borrows
// directly from IntelliJ's bundled _XmlLexer.flex/_HtmlLexer.flex.

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
