"""Typed PDF outlines and editable transclusion proposals.

Source nodes are retained independently of the generated page tree so a shallow
publication does not discard information useful for later navigation.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Literal

import pymupdf
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wtbot.cli.commands.pdf_outline_utils import PageLabel


class DocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ScanRange(DocumentModel):
    first: int = Field(alias="from", ge=1)
    last: int = Field(alias="to", ge=1)

    @model_validator(mode="after")
    def ordered(self) -> ScanRange:
        if self.last < self.first:
            raise ValueError("scan range ends before it starts")
        return self


class SourceNode(DocumentModel):
    id: str
    title: str
    level: int = Field(ge=1)
    scan: int = Field(ge=1)
    pages: list[SourceNode] = Field(default_factory=list)


class SourceLabel(DocumentModel):
    scan: int = Field(ge=1)
    label: str | None


class OutlineSource(DocumentModel):
    kind: Literal["pdf"] = "pdf"
    file: str
    fingerprint: str
    scan_count: int = Field(ge=1)
    labels: list[SourceLabel] = Field(default_factory=list)
    pages: list[SourceNode] = Field(default_factory=list)

    @field_validator("file")
    @classmethod
    def filename_only(cls, value: str) -> str:
        # Also normalise older proposals when they are loaded for sharing.
        filename = Path(value.replace("\\", "/")).name
        if not filename or filename in {".", ".."}:
            raise ValueError("Source file must contain a filename")
        return filename


class Generation(DocumentModel):
    depth: int = Field(default=99, ge=1)
    level_types: dict[int, str] = Field(
        default_factory=lambda: {1: "Part", 2: "Chapter", 3: "Section"}
    )


class WorkMetadata(DocumentModel):
    title: str = ""
    author: str = ""
    translator: str | None = None
    categories: list[str] = Field(default_factory=list)


class ProposedPage(DocumentModel):
    path: str
    title: str
    source_id: str | None = None
    scans: ScanRange | None = None
    pages: list[ProposedPage] = Field(default_factory=list)


class Exclusion(DocumentModel):
    scans: ScanRange
    reason: str = Field(min_length=1)


class TransclusionProposal(DocumentModel):
    schema_version: Literal[1] = 1
    source: OutlineSource
    generation: Generation = Field(default_factory=Generation)
    metadata: WorkMetadata
    pages: list[ProposedPage]
    exclusions: list[Exclusion] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class ResolvedPage:
    title: str
    page: ProposedPage


class GeneratedPage(DocumentModel):
    title: str
    body: str


def clean_title(title: str) -> str:
    return " ".join(title.replace("\x00", "").split())


def extract_pdf(filepath: Path) -> OutlineSource:
    with pymupdf.open(filepath) as doc:
        if not doc.is_pdf or doc.needs_pass:
            raise ValueError("Expected an unlocked PDF")
        if not doc.page_count:
            raise ValueError("PDF contains no pages")
        roots: list[SourceNode] = []
        stack: list[SourceNode] = []
        previous_scan = 0
        for index, (level, title, scan) in enumerate(doc.get_toc()):
            if not 1 <= scan <= doc.page_count:
                raise ValueError(f"Bookmark {title!r} has invalid destination {scan}")
            if scan < previous_scan:
                raise ValueError(f"Bookmark {title!r} goes backwards in scan order")
            while stack and stack[-1].level >= level:
                stack.pop()
            if level != (stack[-1].level + 1 if stack else 1):
                raise ValueError(f"Bookmark {title!r} skips a hierarchy level")
            node = SourceNode(
                id=f"bookmark-{index + 1}",
                title=clean_title(title),
                level=level,
                scan=scan,
            )
            if not node.title:
                raise ValueError(f"Bookmark {index + 1} has an empty title")
            (stack[-1].pages if stack else roots).append(node)
            stack.append(node)
            previous_scan = scan
        labels = [
            SourceLabel(scan=i + 1, label=p.get_label() or None)
            for i, p in enumerate(doc)
        ]
        count = doc.page_count
    with filepath.open("rb") as stream:
        fingerprint = "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()
    return OutlineSource(
        file=filepath.name,
        fingerprint=fingerprint,
        scan_count=count,
        labels=labels,
        pages=roots,
    )


_NAMED = re.compile(
    r"^(?:cover|half title|series page|title page|copyright(?: page)?|contents|table of contents|"
    r"preface|foreword|acknowledg(?:e)?ments|figure credits|notes|references|"
    r"bibliography|index|introduction|appendix)\b",
    re.I,
)
_NUMBERED = re.compile(
    r"^(?:(Book|Part|Chapter|Section|Clause)\s+)?(\d+|[IVXLCDM]+)(?:[.:)\s]|$)", re.I
)


def _number(value: str) -> int:
    label = PageLabel.parse(value)
    if label.number is None or label.number < 1:
        raise ValueError(f"Invalid section number {value!r}")
    return label.number


def propose(
    source: OutlineSource,
    *,
    generation: Generation,
    metadata: WorkMetadata,
) -> TransclusionProposal:
    unresolved: list[str] = []

    def build(nodes: list[SourceNode], end: int) -> list[ProposedPage]:
        result = []
        counter = 0
        for i, node in enumerate(nodes):
            if node.level > generation.depth:
                continue
            # Successive headings on one scan imply that the earlier section
            # occupies part of that scan. Generate it now; section tags can be
            # added during transcription rather than blocking scaffolding.
            final = max(node.scan, nodes[i + 1].scan - 1 if i + 1 < len(nodes) else end)
            kind = generation.level_types.get(node.level, "Section")
            # Part introductions have a structural role despite their prose name.
            part = re.match(
                r"^Introduction to (Part|Book)\s+(\d+|[IVXLCDM]+)\b", node.title, re.I
            )
            explicit = _NUMBERED.match(node.title)
            if part and node.pages:
                counter = _number(part[2])
                path = f"{kind} {counter}"
            elif explicit:
                counter = _number(explicit[2])
                source_kind = explicit[1].title() if explicit[1] else kind
                path = (
                    f"{generation.level_types.get(node.level, source_kind)} {counter}"
                )
            elif _NAMED.match(node.title):
                path = node.title
            else:
                counter += 1
                path = f"{kind} {counter}"
            children = build(node.pages, final) if node.level < generation.depth else []
            own_end = node.pages[0].scan - 1 if children else final
            scans = (
                ScanRange(first=node.scan, last=own_end)
                if own_end >= node.scan
                else None
            )
            result.append(
                ProposedPage(
                    path=path.replace(" ", "_"),
                    title=node.title,
                    source_id=node.id,
                    scans=scans,
                    pages=children,
                )
            )
        return result

    pages = build(source.pages, source.scan_count)
    if not pages:
        pages = [
            ProposedPage(
                path="Text",
                title="Text",
                scans=ScanRange(first=1, last=source.scan_count),
            )
        ]
    elif source.pages[0].scan > 1:
        pages.insert(
            0,
            ProposedPage(
                path="Frontmatter",
                title="Pages before first bookmark",
                scans=ScanRange(first=1, last=source.pages[0].scan - 1),
            ),
        )
    return TransclusionProposal(
        source=source,
        generation=generation,
        metadata=metadata,
        pages=pages,
        unresolved=unresolved,
    )


def _segment(value: str) -> str:
    value = " ".join(value.replace("_", " ").split())
    if (
        not value
        or value in {".", ".."}
        or re.search(r"[\x00-\x1f\x7f/#<>\[\]{}|:]", value)
    ):
        raise ValueError(
            f"Invalid relative page path {value!r}; use nesting for subpages"
        )
    return value.replace(" ", "_")


def _wiki_title(value: str) -> str:
    value = " ".join(value.replace("_", " ").split())
    if (
        not value
        or value.startswith(":")
        or re.search(r"[\x00-\x1f\x7f#<>\[\]{}|]", value)
    ):
        raise ValueError(f"Invalid wiki title {value!r}")
    return value.replace(" ", "_")


def resolve_pages(
    proposal: TransclusionProposal, *, root_page: str | None = None
) -> list[ResolvedPage]:
    root = _wiki_title(root_page) if root_page is not None else ""
    if root.endswith(("/", ":")):
        raise ValueError("Root page must end in a page name")
    result: list[ResolvedPage] = []
    seen: set[str] = set()

    def visit(pages: list[ProposedPage], parent: str) -> None:
        for page in pages:
            segment = _segment(page.path)
            title = f"{parent}/{segment}" if parent else segment
            # First-letter namespace title normalisation; site-aware validation
            # also runs at the application boundary.
            prefix, colon, name = title.partition(":")
            key = (
                f"{prefix.lower()}{colon}{name[:1].upper()}{name[1:]}"
                if colon
                else title[:1].upper() + title[1:]
            )
            if key in seen:
                raise ValueError(f"Duplicate destination {title!r}")
            if len(title.encode("utf-8")) > 255:
                raise ValueError(
                    f"Destination exceeds MediaWiki title length: {title!r}"
                )
            seen.add(key)
            result.append(ResolvedPage(title, page))
            visit(page.pages, title)

    visit(proposal.pages, root)
    return result


def validate_proposal(
    proposal: TransclusionProposal, *, root_page: str | None = None
) -> list[ResolvedPage]:
    if proposal.unresolved:
        raise ValueError("Unresolved boundaries: " + "; ".join(proposal.unresolved))
    pages = resolve_pages(proposal, root_page=root_page)
    if not pages:
        raise ValueError("Proposal contains no pages")
    selections = [(p.page.scans, True) for p in pages if p.page.scans]
    selections.extend((e.scans, False) for e in proposal.exclusions)
    expected = 1
    previous: ScanRange | None = None
    previous_is_content = False
    for selection, is_content in sorted(selections, key=lambda item: item[0].first):
        shared_start = (
            is_content
            and previous_is_content
            and previous is not None
            and previous.first == previous.last == selection.first
        )
        if selection.first != expected and not shared_start:
            raise ValueError(f"Scan coverage gap or overlap at scan {expected}")
        expected = max(expected, selection.last + 1)
        previous = selection
        previous_is_content = is_content
    if expected != proposal.source.scan_count + 1:
        raise ValueError(
            f"Selections must cover all {proposal.source.scan_count} scans"
        )
    for page in pages:
        if page.page.scans is None and not page.page.pages:
            raise ValueError(
                f"Empty leaf {page.title!r} needs content or must be removed"
            )
    # Tree reading order must agree with scan order, independently of coverage.
    ordered = [p.page.scans.first for p in pages if p.page.scans]
    if ordered != sorted(ordered):
        raise ValueError("Page tree reading order disagrees with scan order")
    return pages


def _text(value: str) -> str:
    """Escape template/link delimiters in descriptive source text."""
    return (
        escape(value, quote=False)
        .replace("|", "&#124;")
        .replace("{", "&#123;")
        .replace("}", "&#125;")
        .replace("[", "&#91;")
        .replace("]", "&#93;")
    )


def render(
    proposal: TransclusionProposal, *, root_page: str, index_page: str | None = None
) -> list[GeneratedPage]:
    pages = validate_proposal(proposal, root_page=root_page)
    output = []
    index_title = _wiki_title(index_page or f"Index:{Path(proposal.source.file).name}")
    if not index_title.startswith("Index:") or not index_title.removeprefix("Index:"):
        raise ValueError("index_page must be an Index: title")
    index = index_title.removeprefix("Index:")
    work_title = proposal.metadata.title or root_page.partition(":")[2] or root_page
    work_title = work_title.replace("_", " ")
    for i, resolved in enumerate(pages):
        page = resolved.page
        header = [
            "{{header",
            f" | title = {_text(work_title)}",
            f" | author = {_text(proposal.metadata.author)}",
            f" | section = {_text(page.title)}",
        ]
        if proposal.metadata.translator:
            header.append(f" | translator1 = {_text(proposal.metadata.translator)}")
        for field, neighbour in (("previous", i - 1), ("next", i + 1)):
            if 0 <= neighbour < len(pages):
                other = pages[neighbour]
                header.append(
                    f" | {field} = [[{other.title}|{_text(other.page.title)}]]"
                )
        body = "\n".join([*header, "}}", "{{ppb}}"])
        if page.scans:
            body += f'\n<pages index="{escape(index, quote=True)}" from="{page.scans.first}" to="{page.scans.last}" />'
        for child in page.pages:
            body += (
                f"\n* [[{resolved.title}/{_segment(child.path)}|{_text(child.title)}]]"
            )
        for category in proposal.metadata.categories:
            body += f"\n[[Category:{_wiki_title(category)}]]"
        output.append(GeneratedPage(title=resolved.title, body=body + "\n"))
    return output


def dump_proposal(proposal: TransclusionProposal) -> str:
    return yaml.safe_dump(
        proposal.model_dump(mode="json", by_alias=True),
        sort_keys=False,
        allow_unicode=True,
    )


def load_proposal(path: Path) -> TransclusionProposal:
    return TransclusionProposal.model_validate(yaml.safe_load(path.read_text()))
