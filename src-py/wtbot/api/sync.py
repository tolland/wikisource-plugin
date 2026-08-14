import re
from difflib import unified_diff
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.matching import content_of
from wtbot.model import (
    BatchStatus,
    FetchKind,
    FetchRequest,
    Page,
    Promotion,
    PromotionBatch,
    PromotionIntent,
    PromotionStatus,
    RemoteLink,
    Revision,
    Site,
)
from wtbot.promotion_store import (
    PromotionError,
    abort,
    approve,
    next_staged,
    promotions,
    skip,
    source_is_unchanged,
    stage_batch,
    stage_next_change,
    stage_page,
    target_head_revid,
)
from wtbot.promotion_worker import push_one
from wtbot.site_store import require_credentialed_site, resolve_pair
from wtbot.sync import (
    ScanStatus,
    SyncError,
    SyncPage,
    SyncReport,
    SyncVerdict,
    build_page_report,
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
    linkable: bool = Field(
        default=False,
        description=(
            "Only meaningful on `unlinked`: a comparison finds a matching "
            "revision pair, so `propose --confirm` would link this page. "
            "Reported, never acted on here."
        ),
    )
    actionable: bool = Field(
        description=(
            "True when a push in this direction would write this page -- a "
            "create, or a push onto an asserted anchor. Nothing else."
        )
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
    linkable: int = Field(
        description=(
            "Unlinked pages a `propose --confirm` would link -- work that "
            "would become sync-able, not work a sync would do."
        )
    )
    advisories: list[str] = Field(
        default_factory=list,
        description=(
            "Worth knowing, but not reasons to stop. Kept apart from blockers "
            "because collapsing the two teaches a reader to ignore both."
        ),
    )
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
        linkable=page.linkable,
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
        linkable=report.linkable,
        advisories=report.advisories,
        work_pk=report.work_pk,
        blockers=report.blockers,
        blocked=report.blocked,
    )


@router.post("/report", response_model=SyncReportOut)
def sync_report(
    payload: SyncRequest,
    session: Session = Depends(get_session),
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


# --- single-page promotion --------------------------------------------------
#
# The embarrassment-risk case: pushing a page (or a handful, reviewed one at a
# time) straight back to the public, upstream wiki, with no fan-out to hide
# behind. `/sync/report` compares a whole work; this compares exactly the one
# page named, and nothing else -- no scan check, no sibling pages, no index.


class PageSyncRequest(BaseModel):
    source_label: str | None = Field(
        default=None, description="Registered site the page would be copied *from*."
    )
    target_label: str | None = Field(
        default=None,
        description=(
            "Registered site it would be copied *to*. Omit both to use a "
            "naming convention (local/remote, origin/upstream, "
            "mywikisource/wikisource)."
        ),
    )
    source_title: str = Field(description="Page title on the source site.")
    target_title: str | None = Field(
        default=None,
        description="Only needed when the two sides' titles differ.",
    )


class PageSyncReportOut(BaseModel):
    source_site: str
    target_site: str
    page: SyncPageOut


class NextChangeRequest(BaseModel):
    source_site: str
    target_site: str
    source_title: str
    target_title: str | None = None


class ChangeSourceOut(BaseModel):
    site: str
    title: str
    revid: int
    revision_pk: int
    contributor: str | None = None
    comment: str | None = None


class ChangeTargetOut(BaseModel):
    site: str
    title: str
    base_revid: int | None = None
    url: str


class ChangeReviewOut(BaseModel):
    pk: int
    status: str
    intent: PromotionIntent
    source: ChangeSourceOut
    target: ChangeTargetOut
    submitted_body: str
    diff: str
    transformations: list[str]
    blockers: list[str]


class ChangePushOut(BaseModel):
    pk: int
    status: str
    new_target_revid: int | None = None
    target_revision_url: str | None = None
    edit_summary: str | None = None
    verification_refetch: str
    correspondence_materialized: bool
    error: str | None = None


_SINGLE_CHANGE_LABEL = "single-change"
_PAGEQUALITY_USER = re.compile(
    r"(<pagequality\b[^>]*\buser\s*=\s*[\"'])([^\"']*)([\"'])",
    re.IGNORECASE,
)


def _page_url(site: Site, title: str, revid: int | None = None) -> str:
    if site.api_url:
        split = urlsplit(site.api_url)
        origin = urlunsplit((split.scheme, split.netloc, "", "", ""))
    else:
        origin = f"https://{site.code}.{site.family}.org"
    path = site.articlepath.replace("$1", quote(title.replace(" ", "_"), safe=":/"))
    url = f"{origin}{path}"
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}oldid={revid}" if revid is not None else url


def _transformations(source_body: str, submitted_body: str) -> list[str]:
    if source_body == submitted_body:
        return []
    before = _PAGEQUALITY_USER.search(source_body)
    after = _PAGEQUALITY_USER.search(submitted_body)
    if before and after and before.group(2) != after.group(2):
        return [
            "Rewrote pagequality user from "
            f"{before.group(2)!r} to target push account {after.group(2)!r}."
        ]
    return ["Transformed the source body for submission to the target site."]


def _correspondence_materialized(session: Session, promotion: Promotion) -> bool:
    if promotion.result_revid is None or promotion.target_page_pk is None:
        return False
    target_revision = session.exec(
        select(Revision).where(
            Revision.page_pk == promotion.target_page_pk,
            Revision.revid == promotion.result_revid,
        )
    ).first()
    if target_revision is None:
        return False
    links = session.exec(
        select(RemoteLink).where(
            (RemoteLink.local_revision_pk == promotion.source_revision_pk)
            | (RemoteLink.remote_revision_pk == promotion.source_revision_pk)
        )
    ).all()
    return any(
        target_revision.pk in (link.local_revision_pk, link.remote_revision_pk)
        for link in links
    )


def _change_blockers(session: Session, promotion: Promotion) -> list[str]:
    blockers: list[str] = []
    source_revision = session.get(Revision, promotion.source_revision_pk)
    if source_revision is None or source_revision.page_pk != promotion.source_page_pk:
        blockers.append("The source revision no longer belongs to the source page.")
    if not source_is_unchanged(session, promotion):
        blockers.append("The source moved after this change was calculated.")
    actual_base = target_head_revid(session, promotion)
    if promotion.intent is PromotionIntent.create:
        if actual_base is not None:
            blockers.append(f"The target page now exists at revision {actual_base}.")
    elif actual_base != promotion.base_revid:
        blockers.append(
            "The target moved after this change was calculated "
            f"(expected {promotion.base_revid}, found {actual_base})."
        )
    return blockers


def _change_review(session: Session, promotion: Promotion) -> ChangeReviewOut:
    batch = session.get(PromotionBatch, promotion.batch_pk)
    source_site = session.get(Site, batch.source_site_pk)
    target_site = session.get(Site, batch.target_site_pk)
    source_page = session.get(Page, promotion.source_page_pk)
    source_revision = session.get(Revision, promotion.source_revision_pk)
    source_content = content_of(session, source_revision)
    target_body = ""
    if promotion.target_page_pk is not None:
        target_page = session.get(Page, promotion.target_page_pk)
        from wtbot.revision_store import head_revision

        target_head = head_revision(session, target_page)
        target_content = content_of(session, target_head) if target_head else None
        target_body = target_content.text if target_content else ""
    diff = "".join(
        unified_diff(
            target_body.splitlines(keepends=True),
            promotion.body.splitlines(keepends=True),
            fromfile=f"{promotion.target_title}@{promotion.base_revid or 'missing'}",
            tofile=f"{source_page.title}@{source_revision.revid}",
        )
    )
    blockers = _change_blockers(session, promotion)
    source_body = source_content.text if source_content else ""
    return ChangeReviewOut(
        pk=promotion.pk,
        status="blocked" if blockers else "ready",
        intent=promotion.intent,
        source=ChangeSourceOut(
            site=_site_name(source_site),
            title=source_page.title,
            revid=source_revision.revid,
            revision_pk=source_revision.pk,
            contributor=source_revision.contributor,
            comment=source_revision.comment,
        ),
        target=ChangeTargetOut(
            site=_site_name(target_site),
            title=promotion.target_title,
            base_revid=promotion.base_revid,
            url=_page_url(target_site, promotion.target_title),
        ),
        submitted_body=promotion.body,
        diff=diff,
        transformations=_transformations(source_body, promotion.body),
        blockers=blockers,
    )


def _verification_status(session: Session, promotion: Promotion) -> str:
    batch = session.get(PromotionBatch, promotion.batch_pk)
    requests = session.exec(
        select(FetchRequest).where(
            FetchRequest.site_pk == batch.target_site_pk,
            FetchRequest.title == promotion.target_title,
        )
    ).all()
    if not requests:
        return "not_queued"
    return max(requests, key=lambda row: row.pk or 0).status.value


def _change_result(session: Session, promotion: Promotion) -> ChangePushOut:
    batch = session.get(PromotionBatch, promotion.batch_pk)
    target_site = session.get(Site, batch.target_site_pk)
    status = (
        "already_present"
        if promotion.status is PromotionStatus.skipped
        else promotion.status.value
    )
    return ChangePushOut(
        pk=promotion.pk,
        status=status,
        new_target_revid=promotion.result_revid,
        target_revision_url=(
            _page_url(target_site, promotion.target_title, promotion.result_revid)
            if promotion.result_revid is not None
            else None
        ),
        edit_summary=promotion.comment,
        verification_refetch=_verification_status(session, promotion),
        correspondence_materialized=_correspondence_materialized(session, promotion),
        error=promotion.error_message,
    )


@router.post("/page-report", response_model=PageSyncReportOut)
def sync_page_report(
    payload: PageSyncRequest, session: Session = Depends(get_session)
) -> PageSyncReportOut:
    """Compare one page across two sites: what a push would do to it, and
    nothing else. The single-page counterpart of ``/sync/report``.
    """
    source_site, target_site = resolve_pair(
        session, payload.source_label, payload.target_label
    )
    try:
        page = build_page_report(
            session,
            source_site=source_site,
            target_site=target_site,
            source_title=payload.source_title,
            target_title=payload.target_title,
        )
    except SyncError as exc:
        raise HTTPException(404, str(exc)) from exc
    return PageSyncReportOut(
        source_site=_site_name(source_site),
        target_site=_site_name(target_site),
        page=_page_out(page),
    )


@router.post("/changes/next", response_model=ChangeReviewOut)
def next_change(
    payload: NextChangeRequest,
    session: Session = Depends(get_session),
) -> ChangeReviewOut | Response:
    """Freeze and return one exact source revision for human review."""
    source_site, target_site = resolve_pair(
        session, payload.source_site, payload.target_site
    )
    try:
        page = build_page_report(
            session,
            source_site=source_site,
            target_site=target_site,
            source_title=payload.source_title,
            target_title=payload.target_title,
        )
    except SyncError as exc:
        raise HTTPException(404, str(exc)) from exc

    source_page = session.exec(
        select(Page).where(
            Page.site_pk == source_site.pk,
            Page.title == payload.source_title,
        )
    ).one()
    existing = session.exec(
        select(Promotion)
        .join(PromotionBatch, Promotion.batch_pk == PromotionBatch.pk)
        .where(
            PromotionBatch.label == _SINGLE_CHANGE_LABEL,
            PromotionBatch.source_site_pk == source_site.pk,
            PromotionBatch.target_site_pk == target_site.pk,
            Promotion.source_page_pk == source_page.pk,
            Promotion.target_title == (payload.target_title or payload.source_title),
            Promotion.status == PromotionStatus.staged,
        )
        .order_by(Promotion.pk.desc())
    ).first()
    if existing is not None:
        return _change_review(session, existing)

    awaiting_verification = session.exec(
        select(Promotion)
        .join(PromotionBatch, Promotion.batch_pk == PromotionBatch.pk)
        .where(
            PromotionBatch.label == _SINGLE_CHANGE_LABEL,
            PromotionBatch.source_site_pk == source_site.pk,
            PromotionBatch.target_site_pk == target_site.pk,
            Promotion.source_page_pk == source_page.pk,
            Promotion.target_title == (payload.target_title or payload.source_title),
            Promotion.status == PromotionStatus.pushed,
        )
        .order_by(Promotion.pk.desc())
    ).first()
    if awaiting_verification is not None and not _correspondence_materialized(
        session, awaiting_verification
    ):
        raise HTTPException(
            409,
            "the previous change is pushed but its verification fetch and "
            "source/target correspondence are not complete",
        )

    if page.verdict is SyncVerdict.in_sync:
        return Response(status_code=204)
    try:
        promotion = stage_next_change(
            session,
            page,
            source_site=source_site,
            target_site=target_site,
        )
    except PromotionError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    session.refresh(promotion)
    return _change_review(session, promotion)


@router.post("/changes/{change_pk}/push", response_model=ChangePushOut)
def push_change(
    change_pk: int,
    request: Request,
    session: Session = Depends(get_session),
) -> ChangePushOut:
    """Treat this request as approval and conditionally write once."""
    promotion = session.get(Promotion, change_pk)
    if promotion is None:
        raise HTTPException(404, f"no change {change_pk}")
    batch = session.get(PromotionBatch, promotion.batch_pk)
    if batch.label != _SINGLE_CHANGE_LABEL:
        raise HTTPException(404, f"no single change {change_pk}")
    client_factory = getattr(request.app.state, "client_factory", None)
    if client_factory is None:  # pragma: no cover - app construction wires it
        raise HTTPException(500, "no wiki client factory configured")
    try:
        promotion = push_one(
            session,
            change_pk,
            client_factory,
            require_approval=False,
        )
    except PromotionError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return _change_result(session, promotion)


# --- the push queue ---------------------------------------------------------
#
# A report says what would happen; a batch is somebody deciding it should.
# The two stay separate surfaces because the boundary between them is the only
# place a person's judgement is recorded, and folding "stage" into "report"
# would make looking a consequential act.


class StageRequest(SyncRequest):
    label: str | None = Field(
        default=None, description="A name for this run, to tell it from others."
    )
    page_numbers: list[int] | None = Field(
        default=None,
        description=(
            "Stage only these pages. The usual case: a reviewer works down a "
            "list and stages what they actually looked at. Omit for every "
            "writable page in the report."
        ),
    )


class ApproveRequest(BaseModel):
    approved_by: str = Field(
        description=(
            "Who is signing this off. Stored, not assumed -- 'did a person "
            "agree to this' is exactly the fact an audit wants."
        )
    )


class PushRequest(BaseModel):
    promotion_pk: int | None = Field(
        default=None,
        description="Which page to push. Omit to take the next staged one.",
    )
    force: bool = Field(
        default=False,
        description=(
            "Write even when the source has moved since staging, or the "
            "target's base revid no longer matches. Off by default: both mean "
            "the body under review is not the body being written."
        ),
    )


class PromotionOut(BaseModel):
    pk: int
    source_revision_pk: int
    predecessor_promotion_pk: int | None = None
    page_number: int | None = None
    target_title: str
    intent: PromotionIntent
    status: PromotionStatus
    base_revid: int | None = None
    pre_push_target_revid: int | None = None
    result_revid: int | None = None
    error_message: str | None = None
    body_length: int


class BatchOut(BaseModel):
    pk: int
    label: str | None = None
    status: BatchStatus
    source_site: str
    target_site: str
    source_index_title: str
    target_index_title: str
    approved_by: str | None = None
    work_pk: int | None = None
    counts: dict[str, int] = Field(description="Promotions per status.")
    remaining: int = Field(description="Rows still staged.")
    promotions: list[PromotionOut]


def _promotion_out(row: Promotion) -> PromotionOut:
    return PromotionOut(
        pk=row.pk,
        source_revision_pk=row.source_revision_pk,
        predecessor_promotion_pk=row.predecessor_promotion_pk,
        page_number=row.page_number,
        target_title=row.target_title,
        intent=row.intent,
        status=row.status,
        base_revid=row.base_revid,
        pre_push_target_revid=row.pre_push_target_revid,
        result_revid=row.result_revid,
        error_message=row.error_message,
        body_length=len(row.body),
    )


def _site_name(site: Site) -> str:
    return site.label or f"{site.family}:{site.code}"


def _batch_out(session: Session, batch: PromotionBatch) -> BatchOut:
    rows = promotions(session, batch.pk)
    counts: dict[str, int] = {}
    for row in rows:
        counts[row.status.value] = counts.get(row.status.value, 0) + 1
    return BatchOut(
        pk=batch.pk,
        label=batch.label,
        status=batch.status,
        source_site=_site_name(session.get(Site, batch.source_site_pk)),
        target_site=_site_name(session.get(Site, batch.target_site_pk)),
        source_index_title=batch.source_index_title,
        target_index_title=batch.target_index_title,
        approved_by=batch.approved_by,
        work_pk=batch.index_link_pk,
        counts=counts,
        remaining=counts.get(PromotionStatus.staged.value, 0),
        promotions=[_promotion_out(row) for row in rows],
    )


def _batch(session: Session, batch_pk: int) -> PromotionBatch:
    batch = session.get(PromotionBatch, batch_pk)
    if batch is None:
        raise HTTPException(404, f"no batch {batch_pk}")
    return batch


@router.post("/batches", response_model=BatchOut, status_code=201)
def create_batch(
    payload: StageRequest, session: Session = Depends(get_session)
) -> BatchOut:
    """Stage a push run from what the report says is writable.

    Refuses anything else. An unlinked page a comparison likes, a diverged
    pair, a page the target is ahead on -- staging is the last point at which
    "we are not sure these correspond" is cheap to say, and a queue that
    accepted them would make it expensive.
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
        batch = stage_batch(
            session,
            report,
            source_site=source_site,
            target_site=target_site,
            label=payload.label,
            page_numbers=payload.page_numbers,
        )
    except SyncError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PromotionError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    session.refresh(batch)
    return _batch_out(session, batch)


class StagePageRequest(PageSyncRequest):
    label: str | None = Field(
        default=None, description="A name for this run, to tell it from others."
    )


@router.post("/page-batches", response_model=BatchOut, status_code=201)
def create_page_batch(
    payload: StagePageRequest, session: Session = Depends(get_session)
) -> BatchOut:
    """Stage a single-page push run: this page, this direction, nothing else.

    The ``sync-page`` counterpart of ``POST /sync/batches``, with no fan-out
    -- the batch contains one ordered promotion per source revision after the
    anchor. Everything past staging (approve, push, abort) uses the same batch
    machinery.
    """
    source_site, target_site = resolve_pair(
        session, payload.source_label, payload.target_label
    )
    try:
        page = build_page_report(
            session,
            source_site=source_site,
            target_site=target_site,
            source_title=payload.source_title,
            target_title=payload.target_title,
        )
        batch = stage_page(
            session,
            page,
            source_site=source_site,
            target_site=target_site,
            label=payload.label,
        )
    except SyncError as exc:
        raise HTTPException(404, str(exc)) from exc
    except PromotionError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    session.refresh(batch)
    return _batch_out(session, batch)


@router.get("/batches", response_model=list[BatchOut])
def list_batches(session: Session = Depends(get_session)) -> list[BatchOut]:
    batches = session.exec(
        select(PromotionBatch).order_by(PromotionBatch.pk.desc())
    ).all()
    return [_batch_out(session, batch) for batch in batches]


@router.get("/batches/{batch_pk}", response_model=BatchOut)
def get_batch(batch_pk: int, session: Session = Depends(get_session)) -> BatchOut:
    return _batch_out(session, _batch(session, batch_pk))


@router.post("/batches/{batch_pk}/approve", response_model=BatchOut)
def approve_batch(
    batch_pk: int, payload: ApproveRequest, session: Session = Depends(get_session)
) -> BatchOut:
    """Sign a draft off. Nothing runs without this."""
    batch = _batch(session, batch_pk)
    try:
        approve(session, batch, approved_by=payload.approved_by)
    except PromotionError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return _batch_out(session, batch)


@router.post("/batches/{batch_pk}/push", response_model=BatchOut)
def push_batch_page(
    batch_pk: int,
    request: Request,
    payload: PushRequest | None = None,
    session: Session = Depends(get_session),
) -> BatchOut:
    """Push **one revision step** and return the batch as it now stands.

    One at a time on purpose: the run can be watched, paused and abandoned
    between revisions, the wiki gets one request rather than three hundred,
    and a batch that half-succeeds needs no unpicking because each row carries
    its own outcome.
    """
    payload = payload or PushRequest()
    _batch(session, batch_pk)  # 404 before anything else touches the wiki

    target = payload.promotion_pk
    if target is None:
        upcoming = next_staged(session, batch_pk)
        if upcoming is None:
            raise HTTPException(409, f"batch {batch_pk} has no staged rows left")
        target = upcoming.pk

    client_factory = getattr(request.app.state, "client_factory", None)
    if client_factory is None:  # pragma: no cover - wired at app construction
        raise HTTPException(500, "no wiki client factory configured")

    try:
        push_one(session, target, client_factory, force=payload.force)
    except PromotionError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return _batch_out(session, _batch(session, batch_pk))


@router.post(
    "/batches/{batch_pk}/promotions/{promotion_pk}/skip", response_model=BatchOut
)
def skip_promotion(
    batch_pk: int, promotion_pk: int, session: Session = Depends(get_session)
) -> BatchOut:
    """Drop one revision and its dependent steps without abandoning the run."""
    batch = _batch(session, batch_pk)
    promotion = session.get(Promotion, promotion_pk)
    if promotion is None or promotion.batch_pk != batch_pk:
        raise HTTPException(404, f"no promotion {promotion_pk} in batch {batch_pk}")
    try:
        skip(session, promotion)
    except PromotionError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return _batch_out(session, batch)


@router.post("/batches/{batch_pk}/abort", response_model=BatchOut)
def abort_batch(batch_pk: int, session: Session = Depends(get_session)) -> BatchOut:
    """Stop a run. Staged rows are skipped; pushed rows stay pushed.

    There is no undo: reversing a push means appending another revision, which
    is the rollback item the TODO keeps separate because it is not free.
    """
    batch = _batch(session, batch_pk)
    abort(session, batch)
    session.commit()
    return _batch_out(session, batch)
