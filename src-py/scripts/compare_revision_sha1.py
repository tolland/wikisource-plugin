#!/usr/bin/env python3
"""Compare stored and computed SHA-1 values for two MediaWiki page histories.

This deliberately uses ``BasePage.revisions(content=True)``: the revision's
``sha1`` attribute is the digest stored by MediaWiki, while the main slot's
``*`` value is the content served by the API.  Hashing that value lets us see
when those two notions differ.
"""

# The pywikibot imports intentionally follow the environment configuration.
# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

# Keep this one-off script independent of a local user-config.py.
os.environ.setdefault("PYWIKIBOT_NO_USER_CONFIG", "2")

import pywikibot
from pywikibot.family import AutoFamily
from pywikibot.page._revision import Revision

DEFAULT_TITLE = "Page:Canadian patent 29537.djvu/2"
DEFAULT_SOURCE_API = "https://en.wikisource.org/w/api.php"
DEFAULT_DESTINATION_API = "http://localhost:18581/api.php"
BASE36_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


@dataclass(frozen=True)
class WikiPage:
    label: str
    api_url: str
    title: str


@dataclass(frozen=True)
class HashCandidate:
    description: str
    data: bytes


def base36(value: int) -> str:
    if value == 0:
        return "0"

    result: list[str] = []
    while value:
        value, remainder = divmod(value, 36)
        result.append(BASE36_DIGITS[remainder])
    return "".join(reversed(result))


def hex_to_mediawiki_sha1(hex_digest: str) -> str:
    """Convert an API-style 40-character hex SHA-1 to dump-style base 36."""
    return base36(int(hex_digest, 16)).rjust(31, "0")


def content_sha1(data: bytes) -> tuple[str, str]:
    hex_digest = hashlib.sha1(data).hexdigest()
    return hex_digest, hex_to_mediawiki_sha1(hex_digest)


def main_slot_text(revision: Revision) -> str:
    slots: Mapping[str, Mapping[str, Any]] = revision["slots"]
    main_slot = slots["main"]
    content = main_slot.get("*")
    if not isinstance(content, str):
        raise TypeError(
            f"Revision {revision.revid} has no textual main-slot content: "
            f"{content!r}"
        )
    return content


def transformation_candidates(text: str) -> Iterator[HashCandidate]:
    """Plausible byte representations of API-served ProofreadPage content."""
    without_pagequality_tag = re.sub(
        r"<pagequality\b[^>]*/>",
        "",
        text,
        count=1,
    )
    without_pagequality_header = re.sub(
        r"\A<noinclude><pagequality\b[^>]*/></noinclude>",
        "",
        text,
        count=1,
    )
    text_variants = {
        "UTF-8 as served": text,
        "leading <pagequality> tag removed": without_pagequality_tag,
        "leading <noinclude><pagequality> block removed": (without_pagequality_header),
        "XML entities (text characters)": html.escape(text, quote=False),
        "XML entities (including quotes)": html.escape(text, quote=True),
        "LF converted to CRLF": text.replace("\n", "\r\n"),
        "LF converted to CR": text.replace("\n", "\r"),
        "one trailing LF": f"{text}\n",
        "trailing whitespace removed per line": "\n".join(
            line.rstrip() for line in text.split("\n")
        ),
        "Unicode NFC": unicodedata.normalize("NFC", text),
        "Unicode NFD": unicodedata.normalize("NFD", text),
        "Unicode NFKC": unicodedata.normalize("NFKC", text),
        "Unicode NFKD": unicodedata.normalize("NFKD", text),
    }

    wrapper_match = re.fullmatch(
        r"<noinclude><pagequality\b.*?</noinclude>(.*)" r"<noinclude>.*?</noinclude>",
        text,
        flags=re.DOTALL,
    )
    if wrapper_match:
        text_variants["ProofreadPage body without wrappers"] = wrapper_match.group(1)

    seen: set[bytes] = set()
    for description, variant in text_variants.items():
        data = variant.encode("utf-8")
        if data not in seen:
            seen.add(data)
            yield HashCandidate(description, data)

    for description, encoding in (
        ("UTF-8 with BOM", "utf-8-sig"),
        ("Windows-1252", "windows-1252"),
        ("UTF-16 little-endian", "utf-16-le"),
        ("UTF-16 big-endian", "utf-16-be"),
        ("UTF-32 little-endian", "utf-32-le"),
        ("UTF-32 big-endian", "utf-32-be"),
    ):
        try:
            data = text.encode(encoding)
        except UnicodeEncodeError:
            continue
        if data not in seen:
            seen.add(data)
            yield HashCandidate(description, data)


def print_transformation_attempts(text: str, target_hex: str | None) -> None:
    print("    transformation attempts:")
    found = False
    for candidate in transformation_candidates(text):
        candidate_hex, candidate_base36 = content_sha1(candidate.data)
        matches = candidate_hex == target_hex
        found |= matches
        marker = " MATCH" if matches else ""
        print(
            f"      {candidate.description}: "
            f"{candidate_base36} ({len(candidate.data)} bytes){marker}"
        )
    if not found:
        print("      result: none reproduced the stored SHA-1")


def revisions(page: WikiPage) -> Iterator[Revision]:
    # Site(url=...) cannot infer a family name from a single-label host such as
    # "localhost".  An explicit AutoFamily handles both arbitrary local hosts
    # and the public wiki consistently.
    family = AutoFamily(page.label, page.api_url)
    site = pywikibot.Site(code=family.code, fam=family)
    wiki_page = pywikibot.Page(site, page.title)
    yield from wiki_page.revisions(content=True, reverse=True)


def print_page_history(
    page: WikiPage, *, show_content: bool, try_transformations: bool
) -> None:
    print(f"{page.label}: {page.api_url}")
    print(f"Page: {page.title}")

    for position, revision in enumerate(revisions(page), start=1):
        text = main_slot_text(revision)
        data = text.encode("utf-8")
        computed_hex, computed_base36 = content_sha1(data)
        stored_hex = revision.sha1
        stored_base36 = (
            hex_to_mediawiki_sha1(stored_hex) if stored_hex is not None else None
        )

        print()
        print(f"  revision #{position}")
        print(f"    revid:                 {revision.revid}")
        print(f"    parentid:              {revision.parentid}")
        print(f"    timestamp:             {revision.timestamp}")
        print(f"    user:                  {revision.user}")
        print(f"    main-slot UTF-8 bytes: {len(data)}")
        print(f"    stored SHA-1 hex:      {stored_hex}")
        print(f"    stored SHA-1 base36:   {stored_base36}")
        print(f"    content SHA-1 hex:     {computed_hex}")
        print(f"    content SHA-1 base36:  {computed_base36}")
        print(f"    stored == content:     {stored_hex == computed_hex}")
        if show_content:
            print(f"    main-slot content:     {text!r}")
        if try_transformations and stored_hex != computed_hex:
            print_transformation_attempts(text, stored_hex)

    print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare stored and main-slot SHA-1 values across two wikis."
    )
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--source-api", default=DEFAULT_SOURCE_API)
    parser.add_argument("--destination-api", default=DEFAULT_DESTINATION_API)
    parser.add_argument(
        "--show-content",
        action="store_true",
        help="Also print repr() of every revision's main-slot text.",
    )
    parser.add_argument(
        "--try-transformations",
        action="store_true",
        help="On mismatches, hash plausible alternate encodings and transformations.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pages = (
        WikiPage("source", args.source_api, args.title),
        WikiPage("destination", args.destination_api, args.title),
    )
    for page in pages:
        print_page_history(
            page,
            show_content=args.show_content,
            try_transformations=args.try_transformations,
        )


if __name__ == "__main__":
    main()
