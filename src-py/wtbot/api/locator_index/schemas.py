from typing import Literal

from pydantic import BaseModel

"""Request/response models for `wtbot.api.locator_index.router`, kept apart
from the router so a client-facing description of the shapes doesn't have to
be read alongside the endpoint logic."""


class PageRef(BaseModel):
    """A `Page:` addressed the way the client opens files — by VFS path,
    matching `PageNavEntry` in `page_nav.py`."""

    path: str
    title: str
    scan_page: int


class PageNumberMatch(BaseModel):
    label: str
    confidence: Literal["explicit", "inferred", "unknown"]
    page: PageRef


class SectionMatch(BaseModel):
    section_id: str
    role: Literal["begin", "end", "anchor_template"]
    page: PageRef


class PagelistAssignmentEntry(BaseModel):
    """One explicit `<pagelist>` entry, as written -- the raw source of truth
    [PageIndexEntry.confidence] `"explicit"` is read back from, versus
    `"inferred"` which has no entry here at all."""

    scan_page: int
    kind: Literal["blank", "text", "numeral"]
    text: str | None = None
    style: Literal["arabic", "roman", "highroman"] | None = None
    value: int | None = None


class PageIndexEntry(BaseModel):
    page: PageRef
    label: str | None
    confidence: Literal["explicit", "inferred", "unknown"]


class LocatorIndexDump(BaseModel):
    """Everything this module currently knows about one work, unfiltered."""

    index_title: str
    index_path: str
    pagelist_assignments: list[PagelistAssignmentEntry]
    pages: list[PageIndexEntry]
    sections: list[SectionMatch]
