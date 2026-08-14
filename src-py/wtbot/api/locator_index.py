from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.locator_index import (
    compute_labels,
    parse_pagelist_assignments,
    scan_section_occurrences,
)
from wtbot.model import Page, Site
from wtbot.vfs.paths import WikiPath
from wtbot.vfs.store import PageStore

"""GET /locator-index/{sections,page-numbers,dump} — resolves a back-of-book
locator (a printed page number, or a section/paragraph id) to the `Page:`
that holds it, for building a `{{double link|...}}`-style reference without
hunting through the scan by hand.

Read-only and computed fresh on every call rather than persisted: a work's
whole page set is at most a few hundred `Page:` rows, a local SQLite read
with no network involved, so there is nothing here slow enough to justify a
cache-invalidation problem. Computing fresh also means the result reflects
unsaved local edits (`PageStore.effective_body`) immediately — exactly what
you want while you are the one adding the `<section begin=".."/>` tags this
endpoint is about to help you link to.

All three endpoints accept the *wikisource://* VFS `path` of either the
`Index:` itself or any `Page:` within it (matching `GET /pages/nav`'s own
contract) — so a completion feature running in the transcription editor of
one page can ask about locators for the whole work it belongs to without
first resolving the Index title itself.

`/dump` is the exception to "targeted lookup": it returns everything this
module knows about one work in one call, unfiltered — meant for the viewer's
inspection route and, later, for seeding IntelliJ SDK features that want a
work's whole shape (symbol search, "find usages" of a section id) rather
than one query's answer. An interactive completion feature should still call
the targeted endpoints for the one locator it needs; slurping the whole dump
on every keystroke is the wrong shape even though computing it is cheap.
"""

router = APIRouter(
    prefix="/locator-index", tags=["locator-index"], route_class=DebugLoggingRoute
)


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


def _resolve_index(path: str, session: Session) -> tuple[PageStore, Site, str]:
    store = PageStore(session)
    wiki_path = WikiPath.parse(path)
    if len(wiki_path.segments) < 3:
        raise HTTPException(status_code=400, detail=f"not a work path: {path}")
    site = store.site(wiki_path.family, wiki_path.code)
    if site is None:
        raise HTTPException(
            status_code=404, detail=f"no such site: {wiki_path.family}/{wiki_path.code}"
        )
    index_title = wiki_path.index_title
    if store.page(site, index_title) is None:
        raise HTTPException(status_code=404, detail=f"no such Index: {index_title}")
    return store, site, index_title


def _pages_dir(path: str) -> str:
    wiki_path = WikiPath.parse(path)
    return "/" + "/".join(wiki_path.segments[:3]) + "/Pages"


def _page_ref(store: PageStore, page: Page, pages_dir: str) -> PageRef | None:
    meta = store.proofread_page_meta(page)
    if meta is None or meta.page_number is None:
        return None
    return PageRef(
        path=f"{pages_dir}/{page.title}", title=page.title, scan_page=meta.page_number
    )


def _matches(candidate: str, query: str) -> bool:
    """Exact or prefix — a completion popup calls this with whatever the user
    has typed so far, which is usually a strict prefix of the final id."""
    return candidate == query or candidate.startswith(query)


def _page_refs_by_scan(
    store: PageStore, pages: list[Page], pages_dir: str
) -> dict[int, PageRef]:
    refs: dict[int, PageRef] = {}
    for page in pages:
        ref = _page_ref(store, page, pages_dir)
        if ref is not None:
            refs[ref.scan_page] = ref
    return refs


@router.get("/page-numbers", response_model=list[PageNumberMatch])
def lookup_page_numbers(
    path: str = Query(
        ..., description="wikisource:// VFS path of the Index: or any Page: within it"
    ),
    query: str = Query(
        ..., description="the printed page number/label to match, e.g. '273'"
    ),
    min_confidence: Literal["explicit", "inferred"] = Query(
        "inferred",
        description="'explicit' only returns pages with their own <pagelist> entry; "
        "'inferred' (default) also includes pages counted on from one",
    ),
    limit: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[PageNumberMatch]:
    store, site, index_title = _resolve_index(path, session)
    index_page = store.page(site, index_title)
    assert index_page is not None  # checked in _resolve_index
    pages = store.proofread_pages(site, index_title)
    pages_dir = _pages_dir(path)
    refs = _page_refs_by_scan(store, pages, pages_dir)

    assignments = parse_pagelist_assignments(store.effective_body(index_page))
    labels = compute_labels(assignments, list(refs.keys()))

    allowed = {"explicit"} if min_confidence == "explicit" else {"explicit", "inferred"}
    matches = [
        PageNumberMatch(
            label=label.label, confidence=label.confidence, page=refs[scan_page]
        )
        for scan_page, label in labels.items()
        if label.label is not None
        and label.confidence in allowed
        and _matches(label.label, query)
    ]
    # Exact matches first (the common case: the user typed the whole number),
    # then by page order within a tie.
    matches.sort(key=lambda m: (m.label != query, m.page.scan_page))
    return matches[:limit]


@router.get("/sections", response_model=list[SectionMatch])
def lookup_sections(
    path: str = Query(
        ..., description="wikisource:// VFS path of the Index: or any Page: within it"
    ),
    query: str = Query(
        ..., description="the section/paragraph id to match, e.g. '273' or '3.21'"
    ),
    roles: str = Query(
        "begin,anchor_template",
        description="comma-separated occurrence roles to search: begin, end, anchor_template",
    ),
    limit: int = Query(20, ge=1, le=200),
    session: Session = Depends(get_session),
) -> list[SectionMatch]:
    store, site, index_title = _resolve_index(path, session)
    pages = store.proofread_pages(site, index_title)
    pages_dir = _pages_dir(path)
    wanted_roles = {r.strip() for r in roles.split(",") if r.strip()}

    matches: list[SectionMatch] = []
    for page in pages:
        ref = _page_ref(store, page, pages_dir)
        if ref is None:
            continue
        for occurrence in scan_section_occurrences(
            store.effective_body(page), ref.scan_page
        ):
            if occurrence.role not in wanted_roles or not _matches(
                occurrence.section_id, query
            ):
                continue
            matches.append(
                SectionMatch(
                    section_id=occurrence.section_id, role=occurrence.role, page=ref
                )
            )

    matches.sort(key=lambda m: (m.section_id != query, m.page.scan_page, m.role))
    return matches[:limit]


@router.get("/dump", response_model=LocatorIndexDump)
def dump_locator_index(
    path: str = Query(
        ..., description="wikisource:// VFS path of the Index: or any Page: within it"
    ),
    session: Session = Depends(get_session),
) -> LocatorIndexDump:
    """Everything this module can currently tell about one work: every
    explicit `<pagelist>` entry, every `Page:` with its computed printed-page
    label, and every `<section>`/`{{anchor}}` occurrence — unfiltered. See
    the module docstring for why an interactive feature should prefer the
    targeted endpoints instead.
    """
    store, site, index_title = _resolve_index(path, session)
    index_page = store.page(site, index_title)
    assert index_page is not None  # checked in _resolve_index
    pages = store.proofread_pages(site, index_title)
    pages_dir = _pages_dir(path)
    refs = _page_refs_by_scan(store, pages, pages_dir)

    assignments = parse_pagelist_assignments(store.effective_body(index_page))
    labels = compute_labels(assignments, list(refs.keys()))

    pagelist_entries = [
        PagelistAssignmentEntry(
            scan_page=scan_page,
            kind=assignment.kind,
            text=assignment.text,
            style=assignment.style.value if assignment.style is not None else None,
            value=assignment.value,
        )
        for scan_page, assignment in sorted(assignments.items())
    ]
    page_entries = [
        PageIndexEntry(
            page=refs[scan_page], label=label.label, confidence=label.confidence
        )
        for scan_page, label in sorted(labels.items())
    ]

    sections: list[SectionMatch] = []
    for page in pages:
        ref = _page_ref(store, page, pages_dir)
        if ref is None:
            continue
        for occurrence in scan_section_occurrences(
            store.effective_body(page), ref.scan_page
        ):
            sections.append(
                SectionMatch(
                    section_id=occurrence.section_id, role=occurrence.role, page=ref
                )
            )
    sections.sort(key=lambda m: (m.page.scan_page, m.section_id, m.role))

    return LocatorIndexDump(
        index_title=index_title,
        index_path="/" + "/".join(WikiPath.parse(path).segments[:3]),
        pagelist_assignments=pagelist_entries,
        pages=page_entries,
        sections=sections,
    )
