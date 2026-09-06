from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, func, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.deps import get_session
from wtbot.fetch.revision_store import head_revision
from wtbot.linking.index_link_store import (
    adopt_children,
    link_indexes,
    unlink_index,
    work_for_index_page,
    works_for_sites,
)
from wtbot.linking.page_link_store import find_pair, pair_pages
from wtbot.linking.remote_link_store import LinkError, ladder
from wtbot.matching import (
    LinkProposal,
    MatchOutcome,
    confirm_proposals,
    index_children,
    propose_index_links,
)
from wtbot.model import (
    FetchKind,
    FetchRequest,
    IndexLink,
    IndexMeta,
    LinkOrigin,
    NsRole,
    Page,
    PageLink,
    ProofreadPageMeta,
    RevisionLink,
    Site,
)
from wtbot.site_store import require_credentialed_site, resolve_pair

"""Works: the cross-site unit a reviewer actually navigates.

The page-level surface (``/links``) is complete and unusable as a starting
point. It answers questions about a pair you already know how to name, and a
reviewer arrives knowing only "we track this book against upstream". So this
router is two levels, and nothing more:

1. ``GET /links/works`` -- the works tracked between two sites, and how much of
   each is linked. The list a viewer opens on.
2. ``GET /links/works/{pk}/pages`` -- one work's page pairs, each with what
   comparing them says right now. The list a reviewer works down.

Level 2 recomputes rather than reading a stored verdict. An outcome is a
statement about the revisions currently held, and holding more revisions is
precisely how ``history_exhausted`` gets resolved -- a cached outcome would go
stale on the exact action taken to fix it.

The two resolutions the outcomes call for are here too, because a list of
problems with no way to act on them is a report, not a workflow:

- ``history_exhausted`` and ``quality_differs`` both mean "no anchor in the
  revisions held", and both are usually one fetch away from an anchor.
  ``POST .../fetch-history`` queues that fetch for the pages that need it.
- ``POST .../propose`` re-runs the comparison and, with ``confirm``, writes the
  links that are now assertable.

Deliberately absent: anything that changes a proofreading level. Two sides that
still differ in level after the history is complete disagree about an
assessment, and resolving that is an *edit* -- it goes through the commit path
with a human behind it, not through a link-management endpoint.
"""

router = APIRouter(prefix="/links/works", tags=["works"], route_class=DebugLoggingRoute)


LOCAL_LABEL = Field(default=None, description="Registered site holding our copy.")
REMOTE_LABEL = Field(default=None, description="Registered site holding the other.")

NEEDS_MORE_HISTORY = (MatchOutcome.history_exhausted, MatchOutcome.quality_differs)
"""Outcomes a deeper fetch can turn into a link.

Both say "no anchor in the revisions held". Neither says the pages disagree:
``quality_differs`` is usually one level-bump edit away from an anchor that is
sitting in a revision nobody fetched."""


# --- shapes ----------------------------------------------------------------


class WorkSummary(BaseModel):
    """One tracked work, with the cheap counts a list view needs.

    Deliberately not the per-page outcomes: those cost a content comparison per
    page, and a shelf of thirty works would run thousands to render a menu.
    The counts here are aggregates over rows already stored.
    """

    pk: int
    page_link_pk: int
    created_at: datetime

    local_title: str
    remote_title: str
    local_site: str
    remote_site: str
    local_page_pk: int
    remote_page_pk: int

    pairs: int = Field(description="Page pairs claimed by this work.")
    linked: int = Field(description="Of those, how many have at least one rung.")
    local_pages: int = Field(
        description="Page: children the local index has cached, paired or not."
    )


class WorkList(BaseModel):
    works: list[WorkSummary]


class IndexCandidate(BaseModel):
    """An ``Index:`` page on one site, and whether it is already tracked.

    What the two site columns render. ``work_pk`` is the whole point: a column
    can show tracked works first without the client cross-referencing two
    lists.
    """

    page_pk: int
    title: str
    page_count: int | None = None
    cached_pages: int
    work_pk: int | None = None
    paired_with: str | None = Field(
        default=None, description="The other side's index title, when tracked."
    )


class CandidateList(BaseModel):
    site: str
    site_pk: int
    indexes: list[IndexCandidate]


class LinkWorkRequest(BaseModel):
    local_label: str | None = LOCAL_LABEL
    remote_label: str | None = REMOTE_LABEL
    index_title: str = Field(description="Index title on the local site.")
    remote_index_title: str | None = Field(
        default=None, description="Only needed when the two sides' titles differ."
    )
    pair_pages: bool = Field(
        default=True,
        description=(
            "Also pair the work's Page: children, by page number. On by "
            "default: a tracked work whose pages are not paired can be listed "
            "and nothing else."
        ),
    )
    strict: bool = Field(
        default=False,
        description=(
            "With pair_pages, refuse the work if any page has no counterpart. "
            "Off here, unlike `link pair-index`: this call's primary job is to "
            "track the work, and a partial page-up is reported in `unpaired` "
            "rather than losing the tracking too."
        ),
    )


class LinkWorkResult(BaseModel):
    work: WorkSummary
    created: bool = Field(description="False when the work was already tracked.")
    paired: int = Field(default=0, description="Page pairs created by this call.")
    adopted: int = Field(
        default=0, description="Existing page pairs claimed by the work."
    )
    unpaired: list[str] = Field(
        default_factory=list, description="Local page titles with no counterpart."
    )


class PagePairOut(BaseModel):
    """One page pair inside a work, and what comparing it says right now."""

    pair_pk: int | None = Field(
        default=None, description="Null when the two pages have never been paired."
    )
    page_number: int | None = None
    outcome: MatchOutcome
    proposable: bool
    resolvable_by_fetch: bool = Field(
        description="True when a deeper fetch could turn this into a link."
    )

    local_title: str
    remote_title: str | None = None
    local_revid: int | None = None
    remote_revid: int | None = None
    local_ahead_by: int = 0
    remote_ahead_by: int = 0

    significance: str | None = None
    detail: str | None = None
    rungs: int = 0

    linked: bool = Field(
        default=False,
        description=(
            "Whether any revision link has been asserted for this pair. The "
            "primary fact this page is about -- `outcome` says what a "
            "comparison *would* assert, which is a different question."
        ),
    )
    anchor_is_current: bool = Field(
        default=False,
        description=(
            "Linked, and the newest rung names both sides' heads: nothing "
            "left to do here."
        ),
    )
    needs_attention: bool = Field(
        default=True,
        description=(
            "False exactly when the pair is linked and its anchor is current. "
            "This page exists to link unlinked pages, so a finished row is "
            "noise -- the viewer hides these by default."
        ),
    )


class WorkDetail(BaseModel):
    work: WorkSummary
    pages: list[PagePairOut]
    counts: dict[str, int] = Field(description="Page pairs per outcome.")
    needs_history: int = Field(
        description="Pairs an ordinary fetch-history run would act on."
    )
    needs_attention: int = Field(
        default=0,
        description=(
            "Pairs that are not already linked-and-current -- the ones this "
            "page is for."
        ),
    )
    settled: int = Field(
        default=0, description="Pairs that are linked with their anchor current."
    )


class ProposeWorkRequest(BaseModel):
    confirm: bool = Field(
        default=False, description="Write the links, rather than reporting them."
    )


class ProposeWorkResult(BaseModel):
    counts: dict[str, int]
    confirmed: int = 0


class FetchHistoryRequest(BaseModel):
    revisions: int = Field(
        default=10,
        ge=2,
        description=(
            "Revisions to store per page, counting back from the head. The "
            "default is deliberately modest: the anchor is usually one or two "
            "edits back, and a deep walk over a whole work is a lot of "
            "requests to a wiki that is rate-limiting us."
        ),
    )
    all_pages: bool = Field(
        default=False,
        description=(
            "Queue every page of the work rather than only the ones whose "
            "outcome a deeper history could change."
        ),
    )


class FetchHistoryResult(BaseModel):
    queued: int = Field(description="Fetch requests enqueued.")
    pages: int = Field(description="Page pairs they cover (two sides each).")
    revisions: int
    note: str = Field(
        default=(
            "Queued only. Run a drain (`POST /fetch/drain`) to fetch, then "
            "re-read this work to see the outcomes move."
        )
    )


# --- helpers ---------------------------------------------------------------


def _site_name(site: Site) -> str:
    return site.label or f"{site.family}:{site.code}"


def _index_page(session: Session, site: Site, title: str) -> Page:
    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == title)
    ).first()
    if page is None:
        raise HTTPException(
            404,
            f"{title} is not cached for {_site_name(site)}. Fetch the index "
            "before tracking the work.",
        )
    return page


def _summary(session: Session, work: IndexLink) -> WorkSummary:
    pairing = session.get(PageLink, work.page_link_pk)
    local_page = session.get(Page, pairing.local_page_pk)
    remote_page = session.get(Page, pairing.remote_page_pk)

    pairs = session.exec(
        select(func.count())
        .select_from(PageLink)
        .where(PageLink.index_link_pk == work.pk)
    ).one()
    linked = session.exec(
        select(func.count(func.distinct(RevisionLink.page_link_pk)))
        .select_from(RevisionLink)
        .join(PageLink, PageLink.pk == RevisionLink.page_link_pk)
        .where(PageLink.index_link_pk == work.pk)
    ).one()
    local_site = session.get(Site, local_page.site_pk)

    return WorkSummary(
        pk=work.pk,
        page_link_pk=work.page_link_pk,
        created_at=work.created_at,
        local_title=local_page.title,
        remote_title=remote_page.title,
        local_site=_site_name(local_site),
        remote_site=_site_name(session.get(Site, remote_page.site_pk)),
        local_page_pk=local_page.pk,
        remote_page_pk=remote_page.pk,
        pairs=pairs,
        linked=linked,
        local_pages=len(index_children(session, local_site, local_page.title)),
    )


def _work(session: Session, work_pk: int) -> IndexLink:
    work = session.get(IndexLink, work_pk)
    if work is None:
        raise HTTPException(404, f"no tracked work {work_pk}")
    return work


def _sides(session: Session, work: IndexLink) -> tuple[Page, Page, Site, Site]:
    pairing = session.get(PageLink, work.page_link_pk)
    local_page = session.get(Page, pairing.local_page_pk)
    remote_page = session.get(Page, pairing.remote_page_pk)
    return (
        local_page,
        remote_page,
        session.get(Site, local_page.site_pk),
        session.get(Site, remote_page.site_pk),
    )


def _proposals(session: Session, work: IndexLink) -> list[LinkProposal]:
    local_page, remote_page, local_site, remote_site = _sides(session, work)
    return propose_index_links(
        session,
        local_site=local_site,
        remote_site=remote_site,
        local_index_title=local_page.title,
        remote_index_title=remote_page.title,
    )


def _pair_out(
    session: Session, proposal: LinkProposal, local_site: Site, remote_site: Site
) -> PagePairOut:
    pair_pk: int | None = None
    rungs = 0
    anchor_is_current = False
    local = session.exec(
        select(Page).where(
            Page.site_pk == local_site.pk, Page.title == proposal.local_title
        )
    ).first()
    remote = (
        session.exec(
            select(Page).where(
                Page.site_pk == remote_site.pk, Page.title == proposal.remote_title
            )
        ).first()
        if proposal.remote_title
        else None
    )
    if local is not None and remote is not None:
        pairing = find_pair(session, local.pk, remote.pk)
        if pairing is not None:
            pair_pk = pairing.pk
            ladder_rows = ladder(session, page_pk=local.pk, other_page_pk=remote.pk)
            rungs = len(ladder_rows)
            if ladder_rows:
                anchor = ladder_rows[-1]
                local_head = head_revision(session, local)
                remote_head = head_revision(session, remote)
                anchor_is_current = bool(
                    local_head
                    and remote_head
                    and {anchor.local_revision_pk, anchor.remote_revision_pk}
                    == {local_head.pk, remote_head.pk}
                )

    return PagePairOut(
        pair_pk=pair_pk,
        page_number=proposal.page_number,
        outcome=proposal.outcome,
        proposable=proposal.proposable,
        resolvable_by_fetch=proposal.outcome in NEEDS_MORE_HISTORY,
        local_title=proposal.local_title,
        remote_title=proposal.remote_title,
        local_revid=proposal.local_revid,
        remote_revid=proposal.remote_revid,
        local_ahead_by=proposal.local_ahead_by,
        remote_ahead_by=proposal.remote_ahead_by,
        significance=proposal.significance.value if proposal.significance else None,
        detail=proposal.detail,
        rungs=rungs,
        linked=rungs > 0,
        anchor_is_current=anchor_is_current,
        needs_attention=not (rungs > 0 and anchor_is_current),
    )


# --- level 1: the works ----------------------------------------------------


@router.get("", response_model=WorkList)
def list_works(
    local_label: str | None = None,
    remote_label: str | None = None,
    session: Session = Depends(get_session),
) -> WorkList:
    """Works tracked between two sites.

    With no labels, every tracked work: a viewer that has not chosen its two
    columns yet still has something to show, and the site pair is on each row.
    """
    local_site = remote_site = None
    if local_label or remote_label:
        local_site, remote_site = resolve_pair(session, local_label, remote_label)
    works = works_for_sites(session, local_site, remote_site)
    return WorkList(works=[_summary(session, work) for work in works])


@router.get("/candidates", response_model=CandidateList)
def list_candidates(
    site_pk: int | None = None,
    label: str | None = None,
    session: Session = Depends(get_session),
) -> CandidateList:
    """Every cached ProofreadPage Index on one site, tracked or not.

    One column of the two-column picker. Addressable by pk or by label because
    the viewer holds sites as rows and the CLI holds them as names, and making
    either translate first is a round trip for nothing. ``IndexMeta`` is the
    model-level discriminator: namespace membership alone also admits Index
    subpages and stylesheets, which are not works.
    """
    if site_pk is None and label is None:
        raise HTTPException(400, "name the site: pass site_pk or label")
    site = (
        session.get(Site, site_pk)
        if site_pk is not None
        else session.exec(select(Site).where(Site.label == label)).first()
    )
    if site is None:
        raise HTTPException(404, f"no site {site_pk if site_pk is not None else label}")

    pages = session.exec(
        select(Page, IndexMeta)
        .join(IndexMeta, IndexMeta.page_pk == Page.pk)
        .where(Page.site_pk == site.pk, IndexMeta.site_pk == site.pk)
        .order_by(Page.title)
    ).all()

    counts = dict(
        session.exec(
            select(ProofreadPageMeta.index_page_pk, func.count())
            .join(Page, Page.pk == ProofreadPageMeta.page_pk)
            .where(Page.site_pk == site.pk, Page.namespace_role == NsRole.page)
            .group_by(ProofreadPageMeta.index_page_pk)
        ).all()
    )

    out: list[IndexCandidate] = []
    for page, meta in pages:
        work = work_for_index_page(session, page.pk)
        paired_with = None
        if work is not None:
            pairing = session.get(PageLink, work.page_link_pk)
            other_pk = (
                pairing.remote_page_pk
                if pairing.local_page_pk == page.pk
                else pairing.local_page_pk
            )
            other = session.get(Page, other_pk)
            paired_with = other.title if other else None
        out.append(
            IndexCandidate(
                page_pk=page.pk,
                title=page.title,
                page_count=meta.page_count,
                cached_pages=counts.get(page.pk, 0),
                work_pk=work.pk if work else None,
                paired_with=paired_with,
            )
        )
    return CandidateList(site=_site_name(site), site_pk=site.pk, indexes=out)


@router.post("", response_model=LinkWorkResult, status_code=201)
def create_work(
    payload: LinkWorkRequest, session: Session = Depends(get_session)
) -> LinkWorkResult:
    """Track a work: pair two ``Index:`` pages, and their pages with them.

    Idempotent on the work. Re-posting an existing pair adopts any page pairs
    made since, which is what makes "link the work, then fetch more of it, then
    link it again" behave the way it reads.
    """
    local_site, remote_site = resolve_pair(
        session, payload.local_label, payload.remote_label
    )
    local_index = _index_page(session, local_site, payload.index_title)
    remote_index = _index_page(
        session, remote_site, payload.remote_index_title or payload.index_title
    )

    before = work_for_index_page(session, local_index.pk)
    try:
        work = link_indexes(
            session, local_index, remote_index, origin=LinkOrigin.manual
        )
    except LinkError as exc:
        raise HTTPException(409, str(exc)) from exc

    paired = 0
    unpaired: list[str] = []
    if payload.pair_pages:
        proposals = propose_index_links(
            session,
            local_site=local_site,
            remote_site=remote_site,
            local_index_title=local_index.title,
            remote_index_title=remote_index.title,
        )
        unpaired = [
            p.local_title for p in proposals if p.outcome is MatchOutcome.no_counterpart
        ]
        if unpaired and payload.strict:
            session.rollback()
            raise HTTPException(
                409,
                f"{len(unpaired)} of {len(proposals)} pages have no counterpart "
                f"(first: {unpaired[0]}). Check the remote index title, or "
                "leave strict off to track the work anyway.",
            )
        for proposal in proposals:
            if proposal.outcome is MatchOutcome.no_counterpart:
                continue
            local_page = _page_by_title(session, local_site, proposal.local_title)
            remote_page = _page_by_title(session, remote_site, proposal.remote_title)
            if local_page is None or remote_page is None:  # pragma: no cover
                continue
            if find_pair(session, local_page.pk, remote_page.pk) is None:
                paired += 1
            pairing = pair_pages(
                session, local_page, remote_page, origin=LinkOrigin.title_match
            )
            pairing.index_link_pk = work.pk
            session.add(pairing)

    adopted = adopt_children(session, work)
    session.commit()
    session.refresh(work)

    return LinkWorkResult(
        work=_summary(session, work),
        created=before is None,
        paired=paired,
        adopted=adopted,
        unpaired=unpaired,
    )


def _page_by_title(session: Session, site: Site, title: str | None) -> Page | None:
    if title is None:
        return None
    return session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == title)
    ).first()


@router.delete("/{work_pk}", status_code=200)
def delete_work(
    work_pk: int, cascade: bool = False, session: Session = Depends(get_session)
) -> dict:
    """Stop tracking a work.

    The page pairs are *released* by default, not deleted: "we no longer track
    this against that" says nothing about whether the pages correspond, and the
    pairs carry ladders that are expensive to rebuild. ``cascade=true`` deletes
    them, for the case the untracking is meant to fix -- a work linked to the
    wrong work, where every pair under it was asserted about the wrong pages.
    """
    work = _work(session, work_pk)
    affected = unlink_index(session, work, cascade=cascade)
    session.commit()
    return {
        "deleted": work_pk,
        "cascade": cascade,
        "pairs_deleted" if cascade else "pairs_released": affected,
    }


# --- level 2: the pages inside one work ------------------------------------


@router.get("/{work_pk}", response_model=WorkDetail)
def get_work(work_pk: int, session: Session = Depends(get_session)) -> WorkDetail:
    """One work's page pairs, each with what comparing them says right now.

    Recomputed per call rather than cached. The outcomes are statements about
    the revisions currently held, and the fix for the two most common ones is
    to hold more -- a stored verdict would be stale exactly when it mattered.
    """
    work = _work(session, work_pk)
    _, _, local_site, remote_site = _sides(session, work)

    proposals = _proposals(session, work)
    pages = [_pair_out(session, p, local_site, remote_site) for p in proposals]
    pages.sort(key=lambda row: (row.page_number is None, row.page_number or 0))

    counts: dict[str, int] = {}
    for row in pages:
        counts[row.outcome.value] = counts.get(row.outcome.value, 0) + 1

    return WorkDetail(
        work=_summary(session, work),
        pages=pages,
        counts=counts,
        needs_history=sum(1 for row in pages if row.resolvable_by_fetch),
        needs_attention=sum(1 for row in pages if row.needs_attention),
        settled=sum(1 for row in pages if not row.needs_attention),
    )


@router.post("/{work_pk}/propose", response_model=ProposeWorkResult)
def propose_work(
    work_pk: int,
    payload: ProposeWorkRequest | None = None,
    session: Session = Depends(get_session),
) -> ProposeWorkResult:
    """Re-compare the work's pages and, with ``confirm``, link what can be.

    The step after a fetch-history run: the anchor search now has more to walk,
    so pairs that reported ``history_exhausted`` become ordinary links.
    """
    payload = payload or ProposeWorkRequest()
    work = _work(session, work_pk)
    proposals = _proposals(session, work)

    counts: dict[str, int] = {}
    for proposal in proposals:
        counts[proposal.outcome.value] = counts.get(proposal.outcome.value, 0) + 1

    confirmed = 0
    if payload.confirm:
        confirmed = len(
            confirm_proposals(session, [p for p in proposals if p.proposable])
        )
        # The rungs just written belong to this work; their pairings were
        # created on demand by assert_link and have no pointer yet.
        adopt_children(session, work)
        session.commit()

    return ProposeWorkResult(counts=counts, confirmed=confirmed)


@router.post("/{work_pk}/fetch-history", response_model=FetchHistoryResult)
def fetch_history(
    work_pk: int,
    payload: FetchHistoryRequest | None = None,
    session: Session = Depends(get_session),
) -> FetchHistoryResult:
    """Queue deeper fetches for the pages whose outcome more history could fix.

    ``history_exhausted`` and ``quality_differs`` both mean the anchor search
    ran out of stored revisions, not that the two sides disagree. Both sides
    are queued, because either can be the one holding the revision that
    matches: a local import sits at an older upstream revision, and an upstream
    page can equally sit at an older local one.

    Queues only. Draining is a separate, throttled act -- this endpoint firing
    off hundreds of requests to a rate-limited wiki inside one HTTP call is the
    behaviour the queue exists to prevent.
    """
    payload = payload or FetchHistoryRequest()
    work = _work(session, work_pk)
    _, _, local_site, remote_site = _sides(session, work)

    # Both sides must be able to log in before anything is queued: a drain that
    # fails on credentials does so minutes later, on a row nobody is watching.
    for site in (local_site, remote_site):
        require_credentialed_site(session, site.label or "")

    proposals = _proposals(session, work)
    wanted = [
        p
        for p in proposals
        if p.remote_title is not None
        and (payload.all_pages or p.outcome in NEEDS_MORE_HISTORY)
    ]

    queued = 0
    for proposal in wanted:
        for site, title in (
            (local_site, proposal.local_title),
            (remote_site, proposal.remote_title),
        ):
            session.add(
                FetchRequest(
                    site_pk=site.pk,
                    title=title,
                    kind=FetchKind.page,
                    revisions=payload.revisions,
                )
            )
            queued += 1
    session.commit()

    return FetchHistoryResult(
        queued=queued, pages=len(wanted), revisions=payload.revisions
    )
