from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.site_store import resolve_pair
from wtbot.sync import (
    ScanStatus,
    SyncError,
    SyncPage,
    SyncReport,
    SyncVerdict,
    build_report,
)

"""``POST /sync/report``: what a sync would do, before anything is written.

A read, exposed as a POST because it takes a body of five fields and one of
them is a title with slashes and colons in it. Nothing here mutates either
wiki, and nothing here mutates the local model -- not even the pairings the
report reads. Tracking a work is a separate, deliberate act (``/links/works``),
and a report that quietly created pairings as a side effect of being asked a
question would make "just show me" the most consequential button on the page.

Addressed by **title**, not by a tracked work, because the case that most needs
a report is the one where the target index does not exist yet: there is no
pairing to key on until it does.
"""

router = APIRouter(prefix="/sync", tags=["sync"], route_class=DebugLoggingRoute)


class SyncRequest(BaseModel):
    source_label: str | None = Field(
        default=None, description="Registered site the work would be copied *from*."
    )
    target_label: str | None = Field(
        default=None,
        description=(
            "Registered site it would be copied *to*. Omit both to use a "
            "naming convention (local/remote, origin/upstream, "
            "mywikisource/wikisource)."
        ),
    )
    index_title: str = Field(description="Index title on the source site.")
    target_index_title: str | None = Field(
        default=None,
        description="Only needed when the two sides' index titles differ.",
    )


class ScanCheckOut(BaseModel):
    status: ScanStatus
    detail: str
    source_file: str | None = None
    target_file: str | None = None
    source_sha1: str | None = None
    target_sha1: str | None = None
    source_page_count: int | None = None
    target_page_count: int | None = None
    blocks: bool


class SyncSideOut(BaseModel):
    site: str
    site_pk: int
    index_title: str
    exists: bool
    cached_pages: int
    placeholder_pages: int = Field(
        description=(
            "Pages the index paginates that hold no revision -- slots nobody "
            "has transcribed. Known absent, not unfetched."
        )
    )


class SyncPageOut(BaseModel):
    verdict: SyncVerdict
    page_number: int | None = None
    source_title: str | None = None
    target_title: str | None = None
    pair_pk: int | None = None
    target_is_placeholder: bool = False
    source_revid: int | None = None
    target_revid: int | None = None
    anchor_source_revid: int | None = None
    anchor_target_revid: int | None = None
    rungs: int = 0
    source_ahead_by: int = 0
    target_ahead_by: int = 0
    detail: str | None = None
    actionable: bool = Field(
        description="True when a push in this direction would act on the page."
    )


class SyncReportOut(BaseModel):
    source: SyncSideOut
    target: SyncSideOut
    scan: ScanCheckOut
    pages: list[SyncPageOut]
    counts: dict[str, int]
    actionable: int = Field(description="Pages a push in this direction would write.")
    work_pk: int | None = Field(
        default=None, description="The tracked work, when the pair is tracked."
    )
    blockers: list[str] = Field(
        default_factory=list,
        description=(
            "Reasons a sync should not run as asked. Reported alongside the "
            "page list rather than instead of it: a bare refusal with no work "
            "behind it cannot be argued with."
        ),
    )
    blocked: bool


def _page_out(page: SyncPage) -> SyncPageOut:
    return SyncPageOut(
        verdict=page.verdict,
        page_number=page.page_number,
        source_title=page.source_title,
        target_title=page.target_title,
        pair_pk=page.pair_pk,
        target_is_placeholder=page.target_is_placeholder,
        source_revid=page.source_revid,
        target_revid=page.target_revid,
        anchor_source_revid=page.anchor_source_revid,
        anchor_target_revid=page.anchor_target_revid,
        rungs=page.rungs,
        source_ahead_by=page.source_ahead_by,
        target_ahead_by=page.target_ahead_by,
        detail=page.detail,
        actionable=page.actionable,
    )


def _out(report: SyncReport) -> SyncReportOut:
    return SyncReportOut(
        source=SyncSideOut(**vars(report.source)),
        target=SyncSideOut(**vars(report.target)),
        scan=ScanCheckOut(**vars(report.scan), blocks=report.scan.blocks),
        pages=[_page_out(page) for page in report.pages],
        counts=report.counts,
        actionable=report.actionable,
        work_pk=report.work_pk,
        blockers=report.blockers,
        blocked=report.blocked,
    )


@router.post("/report", response_model=SyncReportOut)
def sync_report(
    payload: SyncRequest, session: Session = Depends(get_session)
) -> SyncReportOut:
    """Compare a work across two sites and report what a sync would do.

    Every verdict is about the revisions currently held, so the report is
    recomputed per call. The scan check runs first and its result is on the
    response whether it passed or not -- "we checked and they match" and "we
    could not check" are different claims, and a report that showed only the
    page list would conflate them.
    """
    source_site, target_site = resolve_pair(
        session, payload.source_label, payload.target_label
    )
    try:
        report = build_report(
            session,
            source_site=source_site,
            target_site=target_site,
            index_title=payload.index_title,
            target_index_title=payload.target_index_title,
        )
    except SyncError as exc:
        raise HTTPException(404, str(exc)) from exc
    return _out(report)
