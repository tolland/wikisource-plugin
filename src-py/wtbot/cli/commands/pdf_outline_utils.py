"""Extract bookmark sections and ProofreadPage numbering from PDF metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

import pymupdf

_ROMAN = re.compile(r"M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})")
_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}


@dataclass(frozen=True)
class PageLabel:
    text: str | None
    number: int | None
    style: str = "normal"

    @classmethod
    def parse(cls, text: str | None) -> PageLabel:
        if not text:
            return cls(None, None)
        if re.fullmatch(r"[0-9]+", text):
            return cls(text, int(text))
        if (text.islower() or text.isupper()) and _ROMAN.fullmatch(text.upper()):
            values = [_ROMAN_VALUES[char] for char in text.upper()]
            number = sum(
                (
                    -value
                    if index + 1 < len(values) and value < values[index + 1]
                    else value
                )
                for index, value in enumerate(values)
            )
            return cls(text, number, "roman" if text.islower() else "highroman")
        return cls(text, None)

    def follows(self, previous: PageLabel) -> bool:
        if self.number is None or previous.number is None:
            return self == previous
        return self.style == previous.style and self.number == previous.number + 1


@dataclass(frozen=True)
class PdfOutlineEntry:
    """A section with zero-based, inclusive page_index and final_index."""

    title: str
    level: int
    page_label: str | None
    page_index: int
    final_index: int

    @property
    def pdf_page(self) -> int:
        return self.page_index + 1


class PdfOutline:
    """Use top-level bookmarks for sections and page labels for numbering.

    Without usable bookmarks, expose the entire document as one section.
    Missing page labels use scan numbers; no printed TOC or OCR is inferred.
    """

    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.page_count = 0
        self._entries: list[PdfOutlineEntry] = []
        self._labels: list[PageLabel] = []
        self.extract_outline()

    @property
    def entries(self) -> list[PdfOutlineEntry]:
        return self._entries

    def extract_outline(self) -> list[PdfOutlineEntry]:
        with pymupdf.open(self.filepath) as doc:
            if not doc.is_pdf:
                raise ValueError("Expected a PDF file")
            if doc.needs_pass:
                raise ValueError(
                    "PDF is password-protected; unlock it before extracting"
                )
            self.page_count = doc.page_count
            self._labels = [PageLabel.parse(page.get_label()) for page in doc]
            bookmarks = sorted(
                (
                    (page - 1, title)
                    for level, title, page in doc.get_toc()
                    if level == 1 and 1 <= page <= self.page_count
                ),
                key=lambda bookmark: bookmark[0],
            )

        # Combine bookmarks sharing a scan so no section has an inverted range.
        starts: list[tuple[int, str]] = []
        for page_index, title in bookmarks:
            if starts and starts[-1][0] == page_index:
                starts[-1] = (page_index, f"{starts[-1][1]} / {title}")
            else:
                starts.append((page_index, title))
        if self.page_count and not starts:
            starts.append((0, "Document"))
        elif starts and starts[0][0] > 0:
            starts.insert(0, (0, "Pages before first bookmark"))

        self._entries = [
            PdfOutlineEntry(
                title=title,
                level=1,
                page_label=self._labels[start].text,
                page_index=start,
                final_index=(
                    starts[index + 1][0] - 1
                    if index + 1 < len(starts)
                    else self.page_count - 1
                ),
            )
            for index, (start, title) in enumerate(starts)
        ]
        return self.entries

    def pagelist(self, entry: PdfOutlineEntry) -> str:
        """Render a section, preserving label transitions and numbering resets."""
        attributes = [f'from="{entry.pdf_page}"', f'to="{entry.final_index + 1}"']
        start = entry.page_index
        while start <= entry.final_index:
            label = self._labels[start]
            end = start
            while end < entry.final_index and self._labels[end + 1].follows(
                self._labels[end]
            ):
                end += 1
            scan = start + 1
            scan_range = f"{scan}to{end + 1}"
            if label.number is not None:
                attributes.append(f'{scan}="{label.number}"')
                if label.style != "normal":
                    attributes.append(f'{scan_range}="{label.style}"')
            elif label.text is not None:
                # A range also keeps literal labels distinct from numeric resets.
                attributes.append(f'{scan_range}="{escape(label.text, quote=True)}"')
            else:
                attributes.append(f'{scan}="{scan}"')
            start = end + 1
        return "<pagelist " + " ".join(attributes) + " />"
