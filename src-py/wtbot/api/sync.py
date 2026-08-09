from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.model import FetchKind, FetchRequest
from wtbot.site_store import require_credentialed_site, resolve_pair
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


class SyncAssetOut(BaseModel):
    """The Index and the File, as things a sync has to account for."""

    kind: str
    source_title: str
    target_title: str
    source_cached: bool
    target_cached: bool
    verdict: SyncVerdict
    detail: str


class FetchPlanItemOut(BaseModel):
    label: str
    title: str
    reason: str


class FetchAssetsResult(BaseModel):
    queued: list["FetchPlanItemOut"]
    note: str = Field(
        default=(
            "Queued only. Run a drain (`POST /fetch/drain`), then re-run the "
            "report: the scan check answers once the uploads are held."
        )
    )


class SyncReportOut(BaseModel):
    source: SyncSideOut
    target: SyncSideOut
    scan: ScanCheckOut
    pages: list[SyncPageOut]
    assets: list[SyncAssetOut] = Field(
        description=(
            "The work's Index: and backing File:. A work is not only its "
            "pages, and the two commonest reasons a sync cannot proceed -- no "
            "index on the target, no scan to check -- are both here."
        )
    )
    fetch_plan: list[FetchPlanItemOut] = Field(
        description=(
            "Fetches that would let the report answer what it currently "
            "cannot. Assets only: the pages have their own, much larger, "
            "fetch action on the work view."
        )
    )
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
        assets=[SyncAssetOut(**vars(asset)) for asset in report.assets],
        fetch_plan=[FetchPlanItemOut(**vars(item)) for item in report.fetch_plan],
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


@router.post("/fetch-assets", response_model=FetchAssetsResult)
def fetch_assets(
    payload: SyncRequest, session: Session = Depends(get_session)
) -> FetchAssetsResult:
    """Queue the report's fetch plan: the work's Index and its backing File.

    The action the report's own gaps call for. A scan check that cannot run is
    not a verdict about the two scans -- it means nobody fetched them -- and a
    target index we have not looked for is not an absent work. Both are settled
    by asking the wiki, and this queues exactly those asks.

    Assets only. The pages are a separate, far larger fetch (on the work view),
    and rolling them together would make "check the scan" cost a whole work's
    worth of throttled requests.

    Queues only: draining stays the separate, throttled step. A title the wiki
    does not hold fails as ``page not found`` on its own queue row, which is
    the answer recorded where the next run can see it.
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

    by_label = {
        (source_site.label or ""): source_site,
        (target_site.label or ""): target_site,
    }
    # Credentials checked before anything is queued: a drain that fails on
    # login does so minutes later, on a row nobody is watching.
    for item in report.fetch_plan:
        require_credentialed_site(session, item.label)

    queued = []
    for item in report.fetch_plan:
        site = by_label[item.label]
        session.add(
            FetchRequest(
                site_pk=site.pk,
                title=item.title,
                # `single` rather than `index`: this is the asset probe, not a
                # fan-out. Fetching the index deeply here would queue every
                # page of a work the caller only asked a yes/no question about.
                kind=FetchKind.single,
            )
        )
        queued.append(FetchPlanItemOut(**vars(item)))
    session.commit()

    return FetchAssetsResult(queued=queued)
