"""Project edited transclusion selections into disjoint Index pagelists."""

from dataclasses import dataclass

from wtbot.cli.commands.pdf_outline_utils import PageLabel, render_pagelist
from wtbot.work_outline import (
    ProposedPage,
    ScanRange,
    TransclusionProposal,
    validate_proposal,
)


@dataclass(frozen=True)
class PagelistSection:
    title: str
    first: int
    last: int


def structure_pagelists(proposal: TransclusionProposal, depth: int = 99) -> str:
    """Use edited pages, not source bookmarks; each scan is listed once.

    Shared-start transclusion selections become one pagelist with joined
    headings. Exclusions still need Index entries: they are scan pages even
    when deliberately omitted from the Book's transclusions.
    """
    if depth < 1:
        raise ValueError("depth must be at least 1")
    validate_proposal(proposal)
    labels = [PageLabel.parse(None) for _ in range(proposal.source.scan_count)]
    seen: set[int] = set()
    for label in proposal.source.labels:
        if label.scan > len(labels) or label.scan in seen:
            raise ValueError(f"Duplicate or out-of-range label scan {label.scan}")
        seen.add(label.scan)
        labels[label.scan - 1] = PageLabel.parse(label.label)

    # Range edits override imported labels. Traverse the full tree even when
    # the displayed pagelist depth is shallower, preserving each range's reset.
    def apply_numbering(pages: list[ProposedPage]) -> None:
        for page in pages:
            selected = page.scans
            if selected is not None and selected.start is not None:
                style = selected.numbering
                if style in {None, "unknown"}:
                    style = "normal"
                for scan in range(selected.first, selected.last + 1):
                    labels[scan - 1] = PageLabel(
                        text=None,
                        number=selected.start + scan - selected.first,
                        style=style,
                    )
            apply_numbering(page.pages)

    apply_numbering(proposal.pages)
    sections: list[PagelistSection] = []

    def selections(page: ProposedPage) -> list[ScanRange]:
        return ([page.scans] if page.scans else []) + [
            selection for child in page.pages for selection in selections(child)
        ]

    def visit(pages: list[ProposedPage], level: int) -> None:
        for page in pages:
            if level == depth:
                ranges = sorted(selections(page), key=lambda r: r.first)
                chunks: list[ScanRange] = []
                for selected in ranges:
                    if chunks and selected.first <= chunks[-1].last + 1:
                        previous = chunks.pop()
                        chunks.append(
                            ScanRange(
                                first=previous.first,
                                last=max(previous.last, selected.last),
                            )
                        )
                    else:
                        chunks.append(selected)
                sections.extend(
                    PagelistSection(page.title, r.first, r.last) for r in chunks
                )
            else:
                if page.scans:
                    sections.append(
                        PagelistSection(page.title, page.scans.first, page.scans.last)
                    )
                visit(page.pages, level + 1)

    visit(proposal.pages, 1)
    sections.extend(
        PagelistSection(
            f"Excluded from transclusion: {e.reason}", e.scans.first, e.scans.last
        )
        for e in proposal.exclusions
    )
    merged: list[PagelistSection] = []
    for section in sorted(sections, key=lambda item: item.first):
        if merged and merged[-1].first == section.first:
            previous = merged.pop()
            merged.append(
                PagelistSection(
                    f"{previous.title} / {section.title}",
                    previous.first,
                    max(previous.last, section.last),
                )
            )
        else:
            merged.append(section)
    expected = 1
    for section in merged:
        if section.first != expected:
            raise ValueError(f"Pagelist coverage gap or overlap at scan {expected}")
        expected = section.last + 1
    if expected != proposal.source.scan_count + 1:
        raise ValueError("Pagelists must cover every source scan")
    return "".join(
        f"{section.title}\n{render_pagelist(labels, section.first, section.last)}\n\n"
        for section in merged
    )
