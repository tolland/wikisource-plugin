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

"""GET /locator-index/{sections,page-numbers} — resolves a back-of-book
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

Both endpoints accept the *wikisource://* VFS `path` of either the `Index:`
itself or any `Page:` within it (matching `GET /pages/nav`'s own contract) —
so a completion feature running in the transcription editor of one page can
ask about locators for the whole work it belongs to without first resolving
the Index title itself.
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
    meta = store.page_meta(page)
    if meta is None or meta.page_number is None:
        return None
    return PageRef(
        path=f"{pages_dir}/{page.title}", title=page.title, scan_page=meta.page_number
    )


def _matches(candidate: str, query: str) -> bool:
    """Exact or prefix — a completion popup calls this with whatever the user
    has typed so far, which is usually a strict prefix of the final id."""
    return candidate == query or candidate.startswith(query)


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

    refs: dict[int, PageRef] = {}
    for page in pages:
        ref = _page_ref(store, page, pages_dir)
        if ref is not None:
            refs[ref.scan_page] = ref

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
