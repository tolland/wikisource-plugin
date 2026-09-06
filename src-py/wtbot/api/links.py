from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.content_model import parse_document
from wtbot.deps import get_session
from wtbot.fetch.revision_store import head_revision
from wtbot.linking.page_link_store import (
    find_pair,
    pair_pages,
    pairs_for_index,
    retract_rungs,
    unpair,
)
from wtbot.linking.remote_link_store import (
    LinkError,
    assert_link,
    current_anchor,
    ladder,
)
from wtbot.matching import (
    LinkProposal,
    MatchOutcome,
    compare_pages,
    confirm_proposals,
    content_of,
    history_is_complete,
    is_same_content,
    propose_index_links,
)
from wtbot.model import (
    MAIN_SLOT,
    Content,
    LinkOrigin,
    Page,
    PageLink,
    ProofreadPageMeta,
    Revision,
    RevisionLink,
    Site,
    Slot,
)
from wtbot.site_store import resolve_pair
from wtbot.timeutil import utcnow

"""Cross-site correspondence: propose, confirm, inspect.

Proposing and confirming are separate calls on purpose. A proposal is a guess
from comparing two heads; a ``RemoteLink`` is an assertion that outlives the
comparison that suggested it, and the design does not auto-confirm guesses
(TODO item 5). ``POST /links/propose`` therefore writes nothing.
"""

router = APIRouter(prefix="/links", tags=["links"], route_class=DebugLoggingRoute)


LOCAL_LABEL = Field(
    default=None,
    description=(
        "Registered site holding our copy. Omit both labels to use a naming "
        "convention (local/remote, origin/upstream, mywikisource/wikisource)."
    ),
)
REMOTE_LABEL = Field(
    default=None, description="Registered site holding the other copy."
)


class LinkPageRequest(BaseModel):
    """Link one named page on each site, by their current head revisions."""

    local_label: str | None = LOCAL_LABEL
    remote_label: str | None = REMOTE_LABEL
    local_title: str = Field(description="Title on the local site")
    remote_title: str | None = Field(
        default=None,
        description="Title on the remote site; defaults to the local title.",
    )
    origin: LinkOrigin = Field(
        default=LinkOrigin.manual,
        description=(
            "How the correspondence is known. `copy` is the strongest claim "
            "(one side was created from the other); `manual` is a human "
            "asserting it; `reconciled` records forward re-anchoring after a "
            "divergence was resolved by hand."
        ),
    )
    force: bool = Field(
        default=False,
        description=(
            "Link even when the heads do not hold the same transcription. "
            "Off by default: a link says the two revisions *are* the same "
            "content, and asserting that of a diverged pair makes every later "
            "comparison lie."
        ),
    )


class ProposeRequest(BaseModel):
    local_label: str | None = LOCAL_LABEL
    remote_label: str | None = REMOTE_LABEL
    index_title: str = Field(description="e.g. 'Index:Some book.djvu'")
    remote_index_title: str | None = Field(
        default=None,
        description="Only needed when the two sides' index titles differ.",
    )
    confirm: bool = Field(
        default=False,
        description=(
            "Write links for every proposable pair. Off by default -- "
            "proposals are proposals."
        ),
    )


class ProposalOut(BaseModel):
    outcome: MatchOutcome
    local_title: str
    remote_title: str | None = None
    page_number: int | None = None
    local_revid: int | None = None
    remote_revid: int | None = None
    significance: str | None = None
    detail: str | None = None
    proposable: bool
    local_ahead_by: int = Field(
        default=0, description="Local revisions newer than the anchor."
    )
    remote_ahead_by: int = Field(
        default=0, description="Remote revisions newer than the anchor."
    )
    anchor_is_heads: bool = Field(
        default=False,
        description="True when the matched pair is both heads: nothing to replay.",
    )


class ProposeResult(BaseModel):
    proposals: list[ProposalOut]
    counts: dict[str, int] = Field(
        description="Proposals per outcome -- the summary worth reading first."
    )
    confirmed: int = Field(default=0, description="Links written; 0 unless confirm.")


class LinkOut(BaseModel):
    pk: int
    local_revision_pk: int
    remote_revision_pk: int
    origin: LinkOrigin


class LadderOut(BaseModel):
    """Every link asserted between two pages, oldest first, plus the anchor.

    The last rung is the current anchor: correspondence is re-established
    forward (a new `reconciled` rung) rather than by editing a broken one, so
    the ladder is the record of what was believed when.
    """

    local_title: str
    remote_title: str
    rungs: list[LinkOut]
    anchor: LinkOut | None = None
    anchor_is_current: bool = Field(
        description=(
            "True when the anchor names both sides' head revisions. False means "
            "work has happened since -- the link is still true, the distance "
            "from it is what says the pages moved."
        )
    )
    local_head_revid: int | None = None
    remote_head_revid: int | None = None
    checked_at: datetime | None = None


def _page(session: Session, site: Site, title: str) -> Page:
    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == title)
    ).first()
    if page is None:
        raise HTTPException(
            404, f"{title} is not cached for site {site.label or site.family}"
        )
    return page


def _out(proposal: LinkProposal) -> ProposalOut:
    return ProposalOut(
        outcome=proposal.outcome,
        local_title=proposal.local_title,
        remote_title=proposal.remote_title,
        page_number=proposal.page_number,
        local_revid=proposal.local_revid,
        remote_revid=proposal.remote_revid,
        significance=(proposal.significance.value if proposal.significance else None),
        detail=proposal.detail,
        proposable=proposal.proposable,
        local_ahead_by=proposal.local_ahead_by,
        remote_ahead_by=proposal.remote_ahead_by,
        anchor_is_heads=proposal.anchor_is_heads,
    )


@router.post("/propose", response_model=ProposeResult)
def propose(
    payload: ProposeRequest, session: Session = Depends(get_session)
) -> ProposeResult:
    """Pair a work's pages across two sites and report what could be linked.

    Writes nothing unless ``confirm``. Pages pair on page number within the
    index rather than on title text, because the two sides' titles can differ
    and the scan offset is what has to line up.
    """
    local_site, remote_site = resolve_pair(
        session, payload.local_label, payload.remote_label
    )
    proposals = propose_index_links(
        session,
        local_site=local_site,
        remote_site=remote_site,
        local_index_title=payload.index_title,
        remote_index_title=payload.remote_index_title,
    )

    confirmed = 0
    if payload.confirm:
        proposable = [p for p in proposals if p.proposable]
        confirmed = len(confirm_proposals(session, proposable))
        session.commit()

    counts: dict[str, int] = {}
    for proposal in proposals:
        counts[proposal.outcome.value] = counts.get(proposal.outcome.value, 0) + 1

    return ProposeResult(
        proposals=[_out(p) for p in proposals],
        counts=counts,
        confirmed=confirmed,
    )


@router.post("/", response_model=LinkOut, status_code=201)
def create_link(
    payload: LinkPageRequest, session: Session = Depends(get_session)
) -> LinkOut:
    """Assert that two named pages' head revisions hold the same content."""
    local_site, remote_site = resolve_pair(
        session, payload.local_label, payload.remote_label
    )
    local_page = _page(session, local_site, payload.local_title)
    remote_page = _page(
        session, remote_site, payload.remote_title or payload.local_title
    )

    proposal = compare_pages(session, local_page, remote_page)
    if proposal.outcome is MatchOutcome.unfetched:
        raise HTTPException(409, proposal.detail or "not fetched")
    if not proposal.proposable and not payload.force:
        raise HTTPException(
            409,
            f"{proposal.outcome.value}: no revision pair holding the same content"
            + (f" -- {proposal.detail}" if proposal.detail else "")
            + ". Fetch more history, reconcile the two sides, or pass force to "
            "assert the heads correspond anyway.",
        )

    try:
        link = assert_link(
            session,
            local_revision_pk=proposal.local_revision_pk,
            remote_revision_pk=proposal.remote_revision_pk,
            origin=payload.origin,
        )
    except LinkError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    session.refresh(link)
    return LinkOut(**link.model_dump())


@router.get("/", response_model=LadderOut)
def get_ladder(
    local_title: str,
    remote_title: str | None = None,
    local_label: str | None = None,
    remote_label: str | None = None,
    session: Session = Depends(get_session),
) -> LadderOut:
    """The ladder for one page pair, and whether its anchor is still current.

    Query parameters rather than a body: this is a read, and it should be
    reachable by pasting a URL.
    """
    local_site, remote_site = resolve_pair(session, local_label, remote_label)
    local_page = _page(session, local_site, local_title)
    remote_page = _page(session, remote_site, remote_title or local_title)

    rungs = ladder(session, page_pk=local_page.pk, other_page_pk=remote_page.pk)
    anchor = current_anchor(
        session, page_pk=local_page.pk, other_page_pk=remote_page.pk
    )
    local_head = head_revision(session, local_page)
    remote_head = head_revision(session, remote_page)

    anchor_is_current = bool(
        anchor
        and local_head
        and remote_head
        and {anchor.local_revision_pk, anchor.remote_revision_pk}
        == {local_head.pk, remote_head.pk}
    )

    return LadderOut(
        local_title=local_page.title,
        remote_title=remote_page.title,
        rungs=[LinkOut(**rung.model_dump()) for rung in rungs],
        anchor=LinkOut(**anchor.model_dump()) if anchor else None,
        anchor_is_current=anchor_is_current,
        local_head_revid=local_head.revid if local_head else None,
        remote_head_revid=remote_head.revid if remote_head else None,
        checked_at=utcnow(),
    )


# --- pairings (CRUD) -------------------------------------------------------
#
# Separate from the revision links because they are a different kind of claim.
# A pairing is about the present and can be wrong, so it has a DELETE; a
# revision link is about two immutable objects and does not.


class PairRequest(BaseModel):
    local_label: str | None = LOCAL_LABEL
    remote_label: str | None = REMOTE_LABEL
    local_title: str = Field(description="Title on the local site")
    remote_title: str | None = Field(
        default=None,
        description="Title on the remote site; defaults to the local title.",
    )
    origin: LinkOrigin = Field(
        default=LinkOrigin.manual,
        description="How the pairing was arrived at.",
    )


class PairOut(BaseModel):
    """A pairing, with enough of each side to render a row without a second
    call -- the viewer lists these, and a list of page pks is not a list."""

    pk: int
    origin: LinkOrigin
    created_at: datetime

    local_page_pk: int
    remote_page_pk: int
    local_title: str
    remote_title: str
    local_site: str
    remote_site: str
    page_number: int | None = None

    rungs: int = Field(description="Revision links asserted under this pairing.")
    anchor_is_current: bool = Field(
        description="True when the newest rung names both sides' heads."
    )


class PairListOut(BaseModel):
    pairs: list[PairOut]


def _site_name(site: Site) -> str:
    return site.label or f"{site.family}:{site.code}"


def _pair_out(session: Session, link: PageLink) -> PairOut:
    local_page = session.get(Page, link.local_page_pk)
    remote_page = session.get(Page, link.remote_page_pk)
    rungs = ladder(
        session, page_pk=link.local_page_pk, other_page_pk=link.remote_page_pk
    )
    anchor = rungs[-1] if rungs else None
    local_head = head_revision(session, local_page)
    remote_head = head_revision(session, remote_page)

    meta = session.exec(
        select(ProofreadPageMeta).where(ProofreadPageMeta.page_pk == link.local_page_pk)
    ).first()

    return PairOut(
        pk=link.pk,
        origin=link.origin,
        created_at=link.created_at,
        local_page_pk=link.local_page_pk,
        remote_page_pk=link.remote_page_pk,
        local_title=local_page.title,
        remote_title=remote_page.title,
        local_site=_site_name(session.get(Site, local_page.site_pk)),
        remote_site=_site_name(session.get(Site, remote_page.site_pk)),
        page_number=meta.page_number if meta else None,
        rungs=len(rungs),
        anchor_is_current=bool(
            anchor
            and local_head
            and remote_head
            and {anchor.local_revision_pk, anchor.remote_revision_pk}
            == {local_head.pk, remote_head.pk}
        ),
    )


@router.get("/pairs", response_model=PairListOut)
def list_pairs(
    index_title: str | None = None,
    local_label: str | None = None,
    remote_label: str | None = None,
    session: Session = Depends(get_session),
) -> PairListOut:
    """Pairings, optionally narrowed to one work.

    Ordered by page number so a work reads in reading order rather than in
    whatever order the pairings happened to be asserted.
    """
    if index_title:
        local_site, _ = resolve_pair(session, local_label, remote_label)
        links = pairs_for_index(session, local_site, index_title)
    else:
        links = list(session.exec(select(PageLink).order_by(PageLink.pk)).all())

    out = [_pair_out(session, link) for link in links]
    out.sort(key=lambda pair: (pair.page_number is None, pair.page_number or 0))
    return PairListOut(pairs=out)


@router.post("/pairs", response_model=PairOut, status_code=201)
def create_pair(
    payload: PairRequest, session: Session = Depends(get_session)
) -> PairOut:
    """Assert that two pages are the same page.

    Does *not* compare content: pairing is the claim that these are two copies
    of one page, which is true of a diverged pair and of one whose other side
    has never been fetched. Whether any revisions correspond is a separate
    question, answered by the revision links under it.
    """
    local_site, remote_site = resolve_pair(
        session, payload.local_label, payload.remote_label
    )
    local_page = _page(session, local_site, payload.local_title)
    remote_page = _page(
        session, remote_site, payload.remote_title or payload.local_title
    )
    try:
        link = pair_pages(session, local_page, remote_page, origin=payload.origin)
    except LinkError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    session.refresh(link)
    return _pair_out(session, link)


@router.get("/pairs/{pair_pk}", response_model=PairOut)
def get_pair(pair_pk: int, session: Session = Depends(get_session)) -> PairOut:
    link = session.get(PageLink, pair_pk)
    if link is None:
        raise HTTPException(404, f"no pairing {pair_pk}")
    return _pair_out(session, link)


@router.delete("/pairs/{pair_pk}", status_code=200)
def delete_pair(pair_pk: int, session: Session = Depends(get_session)) -> dict:
    """Retract a pairing, and the revision links asserted under it.

    The cascade is deliberate: a rung asserted within a pairing nobody now
    claims is not a fact worth keeping, and leaving it would let a later
    pairing inherit assertions made under a different one.
    """
    link = session.get(PageLink, pair_pk)
    if link is None:
        raise HTTPException(404, f"no pairing {pair_pk}")
    removed = unpair(session, link)
    session.commit()
    return {"deleted": pair_pk, "rungs_removed": removed}


@router.delete("/pairs/{pair_pk}/rungs", status_code=200)
def delete_pair_rungs(pair_pk: int, session: Session = Depends(get_session)) -> dict:
    """Retract every revision link under a pairing, keeping the pairing.

    The narrow retraction, and usually the one that is meant. A ladder proposed
    against the wrong other side, or before enough history had been fetched, is
    wrong about the *revisions*; that the two pages are the same page is not in
    doubt, and deleting the pairing to clear the ladder would discard it along
    with everything hanging off it -- the page numbering, and the pair's place
    in a work's listing.
    """
    link = session.get(PageLink, pair_pk)
    if link is None:
        raise HTTPException(404, f"no pairing {pair_pk}")
    removed = retract_rungs(session, link)
    session.commit()
    return {"pairing": pair_pk, "rungs_removed": removed}


# --- the revisions inside one pairing --------------------------------------
#
# The drill-down the two unresolved outcomes need. `quality_differs` and
# `history_exhausted` both end in "no anchor in the history held", which is the
# anchor *search*'s answer, not the whole truth: the search compares each head
# against the other side's history, one side at a time, and deliberately stops
# there. A pair where both sides moved on cannot be resolved by a link the
# search is willing to propose -- but the matching pair may be sitting in the
# two histories, older on both sides, and a person looking at the two columns
# can see it immediately.
#
# So this reports the full cross-product on `comparable_sha1` and lets the
# reviewer assert one. That is the division the whole design rests on: the
# machine proposes only what it is sure of, and a human can assert more.


class RevisionOut(BaseModel):
    """One stored revision of one side, as a row in the drill-down."""

    revision_pk: int
    revid: int
    parent_revid: int | None = None
    timestamp: datetime | None = None
    contributor: str | None = None
    comment: str | None = None
    is_head: bool = False

    comparable_sha1: str | None = Field(
        default=None,
        description=(
            "The model-aware digest. Two revisions with the same value hold the "
            "same content for linking purposes, whichever site they are on."
        ),
    )
    content_sha1: str | None = None
    level: int | None = Field(
        default=None, description="proofread-page quality level, when it has one."
    )
    user: str | None = Field(
        default=None,
        description=(
            "The pagequality username -- an account on that revision's own "
            "wiki. Shown because it explains why the byte hashes differ; never "
            "compared."
        ),
    )
    linked_to: list[int] = Field(
        default_factory=list,
        description="Revision pks on the other side already linked to this one.",
    )


class RevisionMatch(BaseModel):
    """A revision pair holding the same content, whether or not it is linked.

    Found by digest equality, so it is exactly what the anchor search would
    accept -- including the pairs the search will not *propose* because both
    sides have moved on since.
    """

    local_revision_pk: int
    remote_revision_pk: int
    local_revid: int
    remote_revid: int
    local_ahead_by: int = Field(
        description="Local revisions newer than this one -- what would replay out."
    )
    remote_ahead_by: int = Field(
        description="Remote revisions newer than this one -- what would replay in."
    )
    is_heads: bool = Field(description="True when both sides are at this revision.")
    linked: bool = False
    link_pk: int | None = None


class PairRevisionsOut(BaseModel):
    pair_pk: int
    local_title: str
    remote_title: str
    local_site: str
    remote_site: str

    local: list[RevisionOut] = Field(description="Newest first.")
    remote: list[RevisionOut] = Field(description="Newest first.")
    matches: list[RevisionMatch] = Field(
        description="Same-content revision pairs, best (newest) first."
    )
    rungs: list[LinkOut] = Field(description="Links already asserted, oldest first.")
    local_history_complete: bool = Field(
        description="Whether we hold this side back to its first revision."
    )
    remote_history_complete: bool = Field(
        description=(
            "Same for the other side. When either is false, an absent match "
            "means 'we did not look far enough', not 'they never agreed'."
        )
    )


class AssertRungRequest(BaseModel):
    """Link two named revisions of a pairing, by revid."""

    local_revid: int = Field(description="Revision id on the pairing's local side.")
    remote_revid: int = Field(description="Revision id on the pairing's remote side.")
    origin: LinkOrigin = Field(
        default=LinkOrigin.manual,
        description=(
            "`manual` for a human asserting a match the search would not "
            "propose; `reconciled` when the two sides were made identical by "
            "hand and this is the new base."
        ),
    )
    force: bool = Field(
        default=False,
        description=(
            "Assert the link even when the two revisions do not hold the same "
            "content. Off by default: the point of picking revisions by hand is "
            "to find the pair that *does* match."
        ),
    )


def _revision_rows(
    session: Session, page: Page
) -> tuple[list[Revision], dict[int, Content | None]]:
    revisions = list(
        session.exec(
            select(Revision)
            .where(Revision.page_pk == page.pk)
            .order_by(Revision.revid.desc())
        ).all()
    )
    content: dict[int, Content | None] = {}
    for revision in revisions:
        slot = session.get(Slot, (revision.pk, MAIN_SLOT))
        content[revision.pk] = (
            None if slot is None else session.get(Content, slot.content_pk)
        )
    return revisions, content


def _revision_out(
    revision: Revision,
    content: Content | None,
    *,
    head_pk: int | None,
    linked_to: list[int],
) -> RevisionOut:
    level = user = None
    if content is not None:
        document = parse_document(content.text, content.content_model)
        level = getattr(document, "level", None)
        user = getattr(document, "user", None)
    return RevisionOut(
        revision_pk=revision.pk,
        revid=revision.revid,
        parent_revid=revision.parent_revid,
        timestamp=revision.timestamp,
        contributor=revision.contributor,
        comment=revision.comment,
        is_head=revision.pk == head_pk,
        comparable_sha1=content.comparable_sha1 if content else None,
        content_sha1=content.content_sha1 if content else None,
        level=level,
        user=user,
        linked_to=linked_to,
    )


@router.get("/pairs/{pair_pk}/revisions", response_model=PairRevisionsOut)
def pair_revisions(
    pair_pk: int, session: Session = Depends(get_session)
) -> PairRevisionsOut:
    """Both sides' stored revisions, and every same-content pair among them.

    The view that resolves a `quality_differs` page: the heads differ by a
    proofreading level, but an older revision on one side usually holds exactly
    what the other side's head holds, and this shows which. Matching is by
    ``comparable_sha1`` -- no parsing per comparison, and the same predicate the
    anchor search uses, so a match here is a match there.

    Matches are ordered by how little would replay: the pair closest to both
    heads first, since that is the tightest true claim and the one a reviewer
    almost always wants.
    """
    pairing = session.get(PageLink, pair_pk)
    if pairing is None:
        raise HTTPException(404, f"no pairing {pair_pk}")

    local_page = session.get(Page, pairing.local_page_pk)
    remote_page = session.get(Page, pairing.remote_page_pk)
    local_revisions, local_content = _revision_rows(session, local_page)
    remote_revisions, remote_content = _revision_rows(session, remote_page)

    local_head = head_revision(session, local_page)
    remote_head = head_revision(session, remote_page)

    rungs = ladder(session, page_pk=local_page.pk, other_page_pk=remote_page.pk)
    linked_pairs: dict[tuple[int, int], RevisionLink] = {}
    linked_from: dict[int, list[int]] = {}
    for rung in rungs:
        for near, far in (
            (rung.local_revision_pk, rung.remote_revision_pk),
            (rung.remote_revision_pk, rung.local_revision_pk),
        ):
            linked_pairs[(near, far)] = rung
            linked_from.setdefault(near, []).append(far)

    matches: list[RevisionMatch] = []
    remote_by_digest: dict[str, list[tuple[int, Revision]]] = {}
    for offset, revision in enumerate(remote_revisions):
        content = remote_content.get(revision.pk)
        if content is None or content.comparable_sha1 is None:
            continue
        remote_by_digest.setdefault(content.comparable_sha1, []).append(
            (offset, revision)
        )

    for local_offset, revision in enumerate(local_revisions):
        content = local_content.get(revision.pk)
        if content is None or content.comparable_sha1 is None:
            continue
        for remote_offset, other in remote_by_digest.get(content.comparable_sha1, []):
            rung = linked_pairs.get((revision.pk, other.pk))
            matches.append(
                RevisionMatch(
                    local_revision_pk=revision.pk,
                    remote_revision_pk=other.pk,
                    local_revid=revision.revid,
                    remote_revid=other.revid,
                    local_ahead_by=local_offset,
                    remote_ahead_by=remote_offset,
                    is_heads=local_offset == 0 and remote_offset == 0,
                    linked=rung is not None,
                    link_pk=rung.pk if rung else None,
                )
            )
    matches.sort(key=lambda m: (m.local_ahead_by + m.remote_ahead_by, m.local_ahead_by))

    return PairRevisionsOut(
        pair_pk=pair_pk,
        local_title=local_page.title,
        remote_title=remote_page.title,
        local_site=_site_name(session.get(Site, local_page.site_pk)),
        remote_site=_site_name(session.get(Site, remote_page.site_pk)),
        local=[
            _revision_out(
                revision,
                local_content.get(revision.pk),
                head_pk=local_head.pk if local_head else None,
                linked_to=linked_from.get(revision.pk, []),
            )
            for revision in local_revisions
        ],
        remote=[
            _revision_out(
                revision,
                remote_content.get(revision.pk),
                head_pk=remote_head.pk if remote_head else None,
                linked_to=linked_from.get(revision.pk, []),
            )
            for revision in remote_revisions
        ],
        matches=matches,
        rungs=[LinkOut(**rung.model_dump()) for rung in rungs],
        local_history_complete=history_is_complete(session, local_page),
        remote_history_complete=history_is_complete(session, remote_page),
    )


@router.post("/pairs/{pair_pk}/rungs", response_model=LinkOut, status_code=201)
def assert_pair_rung(
    pair_pk: int,
    payload: AssertRungRequest,
    session: Session = Depends(get_session),
) -> LinkOut:
    """Link two revisions of a pairing, chosen by hand.

    The action the drill-down exists for. The anchor search proposes only pairs
    it can reach from a head, so a page where both sides moved on after their
    last agreement has no proposal even when the agreeing pair is plainly there
    in the two histories. A reviewer who can see it can assert it.

    Still checked: the two revisions must hold the same content unless
    ``force``. Picking by hand is meant to find the pair that matches, not to
    bypass the question -- and a false rung is inherited by everything above it.
    """
    pairing = session.get(PageLink, pair_pk)
    if pairing is None:
        raise HTTPException(404, f"no pairing {pair_pk}")

    local = _revision_by_id(session, pairing.local_page_pk, payload.local_revid)
    remote = _revision_by_id(session, pairing.remote_page_pk, payload.remote_revid)

    if not payload.force:
        local_content = content_of(session, local)
        remote_content = content_of(session, remote)
        if local_content is None or remote_content is None:
            raise HTTPException(
                409, "a chosen revision has no cached content to compare"
            )
        if not is_same_content(local_content, remote_content):
            raise HTTPException(
                409,
                f"revisions {payload.local_revid} and {payload.remote_revid} do "
                "not hold the same content. Pick a pair the drill-down reports "
                "as matching, or pass force to assert this one anyway.",
            )

    try:
        link = assert_link(
            session,
            local_revision_pk=local.pk,
            remote_revision_pk=remote.pk,
            origin=payload.origin,
            page_link_pk=pairing.pk,
        )
    except LinkError as exc:
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    session.refresh(link)
    return LinkOut(**link.model_dump())


def _revision_by_id(session: Session, page_pk: int, revid: int) -> Revision:
    revision = session.exec(
        select(Revision).where(Revision.page_pk == page_pk, Revision.revid == revid)
    ).first()
    if revision is None:
        raise HTTPException(
            404,
            f"revision {revid} is not cached for this pairing's page. Fetch more "
            "history, or pick a revision the drill-down lists.",
        )
    return revision


@router.delete("/{link_pk}", status_code=200)
def delete_link(link_pk: int, session: Session = Depends(get_session)) -> dict:
    """Remove one revision link.

    The one exception to append-only, and it is for mistakes rather than for
    history: a rung asserted in error is not superseded by a later one, it was
    never true. Correcting a *changed* correspondence is still a new rung.

    The pairing is untouched, and the response names it: retracting a rung says
    the two *revisions* do not correspond, never that the two pages do not.
    """
    link = session.get(RevisionLink, link_pk)
    if link is None:
        raise HTTPException(404, f"no link {link_pk}")
    pairing = link.page_link_pk
    session.delete(link)
    session.commit()
    return {"deleted": link_pk, "pairing": pairing}


class PairIndexRequest(BaseModel):
    local_label: str | None = LOCAL_LABEL
    remote_label: str | None = REMOTE_LABEL
    index_title: str = Field(description="e.g. 'Index:Some book.djvu'")
    remote_index_title: str | None = Field(
        default=None,
        description="Only needed when the two sides' index titles differ.",
    )
    strict: bool = Field(
        default=True,
        description=(
            "Refuse the whole work if any page has no counterpart. On by "
            "default: a work that does not line up is usually a wrong `--to` "
            "or a different scan, and pairing the pages that happen to match "
            "buries that."
        ),
    )


class PairIndexResult(BaseModel):
    paired: int = Field(description="Pairings that now exist for this work.")
    created: int = Field(description="How many of those this call created.")
    unpaired: list[str] = Field(
        default_factory=list,
        description="Local titles with no counterpart on the other side.",
    )


@router.post("/pairs/index", response_model=PairIndexResult, status_code=201)
def pair_index(
    payload: PairIndexRequest, session: Session = Depends(get_session)
) -> PairIndexResult:
    """Pair a whole work's pages, before any content is compared.

    This is the step that makes a work navigable: the viewer drills an index
    down to its page pairs, and a pair has to exist for a diverged page to be
    listed at all. Content comparison comes after, per pair.

    Pages that do not line up are an error by default rather than a silent
    omission -- a work missing half its counterparts is nearly always a wrong
    `--to` or a different scan, and that is worth stopping for.
    """
    local_site, remote_site = resolve_pair(
        session, payload.local_label, payload.remote_label
    )
    proposals = propose_index_links(
        session,
        local_site=local_site,
        remote_site=remote_site,
        local_index_title=payload.index_title,
        remote_index_title=payload.remote_index_title,
    )
    if not proposals:
        raise HTTPException(
            404,
            f"no pages found for {payload.index_title} on "
            f"{_site_name(local_site)}. Fetch the work first.",
        )

    unpaired = [
        p.local_title for p in proposals if p.outcome is MatchOutcome.no_counterpart
    ]
    if unpaired and payload.strict:
        raise HTTPException(
            409,
            f"{len(unpaired)} of {len(proposals)} pages have no counterpart "
            f"(first: {unpaired[0]}). Check --to, or pass strict=false to pair "
            "the rest anyway.",
        )

    created = 0
    for proposal in proposals:
        if proposal.outcome is MatchOutcome.no_counterpart:
            continue
        local_page = _page(session, local_site, proposal.local_title)
        remote_page = _page(session, remote_site, proposal.remote_title)
        before = find_pair(session, local_page.pk, remote_page.pk)
        pair_pages(session, local_page, remote_page, origin=LinkOrigin.title_match)
        if before is None:
            created += 1
    session.commit()

    return PairIndexResult(
        paired=len(proposals) - len(unpaired), created=created, unpaired=unpaired
    )
