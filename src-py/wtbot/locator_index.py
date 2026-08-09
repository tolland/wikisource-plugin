import re
from dataclasses import dataclass
from enum import Enum
from typing import Literal

"""Back-of-book locator resolution — pure text/computation, no DB or FastAPI.

Transcribing a back-of-book index ("ACCELERATION, 273") or a proposition list
(Tractatus's "3.21") means answering "what does this reference point at?" —
which `Page:` scan holds it, so the transcriber can open it, read the source,
and build a `{{double link|...}}` (or similar) to it. Two independent
locator schemes are in scriptural/scholarly use, corresponding to the two
kinds of back-matter this module resolves:

  - a **printed page number** ("273"), resolved via the Index's own
    `<pagelist>` tag (see [parse_pagelist_assignments] / [compute_labels]);
  - a **section/paragraph id** ("p-273", "3.21"), resolved by finding which
    `Page:` carries a `<section begin="...">` for it (see
    [scan_section_occurrences]) — the numbered-paragraph convention Hertz and
    the Tractatus both use, where the "page number" scheme doesn't apply at
    all (a paragraph reference names a *paragraph*, not a page).

`wtbot.api.locator_index` is the thin FastAPI layer that loads a work's pages
from the cache (via `PageStore`, using `effective_body` so local unsaved
edits are visible) and calls into this module — kept separate so the actual
parsing logic is unit-testable without a database.
"""


# ---------------------------------------------------------------------------
# Roman numerals
# ---------------------------------------------------------------------------

_ROMAN_TABLE: list[tuple[int, str]] = [
    (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
    (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
    (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
]  # fmt: skip

_ROMAN_VALUES: dict[str, int] = {
    "i": 1,
    "v": 5,
    "x": 10,
    "l": 50,
    "c": 100,
    "d": 500,
    "m": 1000,
}


def to_roman(value: int, upper: bool = False) -> str:
    """Lowercase (or [upper]) roman numeral for [value]. Falls back to the
    plain decimal string for non-positive input — roman numerals have no
    zero, and a front-matter page numbered "0" or negative is a modelling
    error elsewhere, not something to crash rendering over."""
    if value <= 0:
        return str(value)
    remaining = value
    parts: list[str] = []
    for n, sym in _ROMAN_TABLE:
        while remaining >= n:
            parts.append(sym)
            remaining -= n
    rendered = "".join(parts)
    return rendered.upper() if upper else rendered


def from_roman(text: str) -> int | None:
    """Parses a roman numeral, or None if [text] isn't a well-formed one —
    the gate that tells "xi" (a page explicitly labelled with a roman
    numeral) apart from "adv" or "half-title" (a literal text label that
    merely happens to be made of letters). Round-trips through [to_roman] to
    reject non-canonical strings ("iiii", "vv") rather than parse them
    loosely; a real page label should be one a human actually wrote."""
    lowered = text.lower()
    if not lowered or any(ch not in _ROMAN_VALUES for ch in lowered):
        return None
    total = 0
    previous = 0
    for ch in reversed(lowered):
        v = _ROMAN_VALUES[ch]
        if v < previous:
            total -= v
        else:
            total += v
            previous = v
    if to_roman(total) != lowered:
        return None
    return total


# ---------------------------------------------------------------------------
# <pagelist> parsing
# ---------------------------------------------------------------------------


class NumeralStyle(str, Enum):
    arabic = "arabic"
    roman = "roman"
    highroman = "highroman"


@dataclass(frozen=True)
class PagelistAssignment:
    """One scan page's explicit `<pagelist>` entry (`N=value` or the page's
    share of an `NtoM=value` range), already classified. [kind] `numeral`
    covers a bare integer ("48"), a literal roman numeral ("xi"), and the
    style-switch keywords ("roman"/"highroman", which restart the counter at
    i/I from this page)."""

    scan_page: int
    kind: Literal["blank", "text", "numeral"]
    text: str | None = None
    style: NumeralStyle | None = None
    value: int | None = None


@dataclass(frozen=True)
class PageNumberLabel:
    """A scan page's resolved printed-page label.

    [confidence] is `"explicit"` when this scan page has its own
    `<pagelist>` entry, `"inferred"` when it was computed by counting on from
    the nearest earlier numeral anchor, and `"unknown"` when there is no
    preceding numeral anchor to count from at all — deliberately not a
    guess: a completion feature should not offer a fabricated number.
    """

    scan_page: int
    label: str | None
    confidence: Literal["explicit", "inferred", "unknown"]


# Tolerates the unquoted attribute style real Index pages are pasted in
# (`from=1 to=8`) as well as quoted values. The digit-run key requirement
# ("from"/"to" don't start with a digit) is what keeps this from ever
# misreading the tag's own `from=`/`to=` bounds as a page assignment --
# no separate exclusion list needed.
_PAGELIST_TAG_RE = re.compile(r"<pagelist\b([^>]*)/>", re.IGNORECASE)
_ASSIGNMENT_RE = re.compile(
    r'\b(\d+)(?:to(\d+))?\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s/>]+))'
)


def _classify_value(scan_page: int, raw: str) -> PagelistAssignment:
    text = raw.strip()
    if text == "-":
        return PagelistAssignment(scan_page, kind="blank")
    lowered = text.lower()
    if lowered == "roman":
        return PagelistAssignment(
            scan_page, kind="numeral", style=NumeralStyle.roman, value=1
        )
    if lowered == "highroman":
        return PagelistAssignment(
            scan_page, kind="numeral", style=NumeralStyle.highroman, value=1
        )
    if text.isdigit():
        return PagelistAssignment(
            scan_page, kind="numeral", style=NumeralStyle.arabic, value=int(text)
        )
    roman_value = from_roman(text)
    if roman_value is not None:
        style = NumeralStyle.highroman if text.isupper() else NumeralStyle.roman
        return PagelistAssignment(
            scan_page, kind="numeral", style=style, value=roman_value
        )
    return PagelistAssignment(scan_page, kind="text", text=text)


def parse_pagelist_assignments(index_body: str) -> dict[int, PagelistAssignment]:
    """Every explicit per-page `<pagelist>` entry on an Index page, across
    every `<pagelist>` tag found (a work is commonly split into several, one
    per front-matter/chapter block — see the Hertz example this module was
    built against). Later tags win on a page number reused by more than one
    (shouldn't happen in a well-formed Index, but silently picking the last
    is safer than raising over a paste error mid-transcription).
    """
    assignments: dict[int, PagelistAssignment] = {}
    for tag_match in _PAGELIST_TAG_RE.finditer(index_body):
        for m in _ASSIGNMENT_RE.finditer(tag_match.group(1)):
            start_s, end_s, dq, sq, bare = m.groups()
            value = dq if dq is not None else (sq if sq is not None else bare)
            if value is None:
                continue
            start = int(start_s)
            end = int(end_s) if end_s else start
            for scan_page in range(start, end + 1):
                assignments[scan_page] = _classify_value(scan_page, value)
    return assignments


def compute_labels(
    assignments: dict[int, PagelistAssignment],
    scan_pages: list[int],
) -> dict[int, PageNumberLabel]:
    """Resolves a printed-page label for each of [scan_pages].

    A page with its own entry uses it verbatim (`"explicit"`). Otherwise the
    label is counted on from the nearest earlier `numeral` entry — a `blank`
    or `text` entry (a title page, "-") does not shift this basis, so a
    half-title or cover page sitting between two content pages does not
    throw off the count that follows it. This is the one inferential rule in
    this module rather than a straight readback of the wikitext; it matches
    every example this was built against, but is worth checking against a
    real rendered Index before trusting it on a work with an unusual
    numbering scheme.
    """
    numeral_anchors = sorted(
        (a for a in assignments.values() if a.kind == "numeral"),
        key=lambda a: a.scan_page,
    )
    labels: dict[int, PageNumberLabel] = {}
    for scan_page in sorted(set(scan_pages)):
        own = assignments.get(scan_page)
        if own is not None:
            if own.kind == "blank":
                labels[scan_page] = PageNumberLabel(scan_page, None, "explicit")
            elif own.kind == "text":
                labels[scan_page] = PageNumberLabel(scan_page, own.text, "explicit")
            else:
                labels[scan_page] = PageNumberLabel(
                    scan_page, _render(own.value, own.style), "explicit"
                )
            continue

        basis = None
        for anchor in numeral_anchors:
            if anchor.scan_page > scan_page:
                break
            basis = anchor
        if basis is None:
            labels[scan_page] = PageNumberLabel(scan_page, None, "unknown")
            continue
        assert basis.value is not None and basis.style is not None
        value = basis.value + (scan_page - basis.scan_page)
        labels[scan_page] = PageNumberLabel(
            scan_page, _render(value, basis.style), "inferred"
        )
    return labels


def _render(value: int, style: NumeralStyle) -> str:
    if style == NumeralStyle.arabic:
        return str(value)
    return to_roman(value, upper=style == NumeralStyle.highroman)


# ---------------------------------------------------------------------------
# Section/paragraph anchors
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionOccurrence:
    """One place a section/paragraph id is anchored in a `Page:`'s wikitext.

    `begin`/`end` come from Labeled Section Transclusion's own
    `<section begin=".."/>`/`<section end=".."/>` pair; `anchor_template`
    comes from a companion `{{anchor|..}}` — LST itself creates no HTML
    anchor a reader's browser can jump to, so transcribers commonly add one
    alongside the section tag purely so `#id` fragment links resolve. Kept
    as its own role rather than folded into `begin`: a section id with a
    `begin` but no `anchor_template` is worth flagging when generating a
    fragment link, since the link would not actually land anywhere.
    """

    section_id: str
    scan_page: int
    role: Literal["begin", "end", "anchor_template"]


_SECTION_BEGIN_RE = re.compile(
    r'<section\s+begin\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE
)
_SECTION_END_RE = re.compile(r'<section\s+end\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_ANCHOR_TEMPLATE_RE = re.compile(
    r"\{\{\s*anchor\s*\|\s*([^{}|]+?)\s*(?:\||\})", re.IGNORECASE
)


def scan_section_occurrences(body: str, scan_page: int) -> list[SectionOccurrence]:
    """Every `<section begin/end>` and `{{anchor|..}}` on one `Page:`'s body,
    tagged with which scan page it came from. The direct analogue of the
    `re.compile(r'<section begin="([0-9.]+)"')` regex already used to build
    the Tractatus section index by hand — generalised to also see `end` and
    `anchor_template`, and to accept single-quoted attributes.
    """
    occurrences = [
        SectionOccurrence(m.group(1), scan_page, "begin")
        for m in _SECTION_BEGIN_RE.finditer(body)
    ]
    occurrences += [
        SectionOccurrence(m.group(1), scan_page, "end")
        for m in _SECTION_END_RE.finditer(body)
    ]
    occurrences += [
        SectionOccurrence(m.group(1).strip(), scan_page, "anchor_template")
        for m in _ANCHOR_TEMPLATE_RE.finditer(body)
    ]
    return occurrences
