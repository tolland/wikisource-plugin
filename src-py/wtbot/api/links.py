from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from wtbot.deps import get_session
from wtbot.matching import (
    LinkProposal,
    MatchOutcome,
    compare_pages,
    confirm_proposals,
    propose_index_links,
)
from wtbot.model import LinkOrigin, Page, Site
from wtbot.remote_link_store import LinkError, assert_link, current_anchor, ladder
from wtbot.revision_store import head_revision
from wtbot.timeutil import utcnow

"""Cross-site correspondence: propose, confirm, inspect.

Proposing and confirming are separate calls on purpose. A proposal is a guess
from comparing two heads; a ``RemoteLink`` is an assertion that outlives the
comparison that suggested it, and the design does not auto-confirm guesses
(TODO item 5). ``POST /links/propose`` therefore writes nothing.
"""

router = APIRouter(prefix="/links", tags=["links"])


class SiteRef(BaseModel):
    family: str = Field(description="pywikibot family, e.g. 'wikisource'")
    code: str = Field(description="pywikibot language code, e.g. 'en'")


class LinkPageRequest(BaseModel):
    """Link one named page on each site, by their current head revisions."""

    local: SiteRef
    remote: SiteRef
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
    local: SiteRef
    remote: SiteRef
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


def _site(session: Session, ref: SiteRef) -> Site:
    site = session.exec(
        select(Site).where(Site.family == ref.family, Site.code == ref.code)
    ).first()
    if site is None:
        raise HTTPException(404, f"no site {ref.family}:{ref.code}")
    return site


def _page(session: Session, site: Site, title: str) -> Page:
    page = session.exec(
        select(Page).where(Page.site_pk == site.pk, Page.title == title)
    ).first()
    if page is None:
        raise HTTPException(404, f"{title} is not cached for {site.family}:{site.code}")
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
    local_site = _site(session, payload.local)
    remote_site = _site(session, payload.remote)
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
    local_site = _site(session, payload.local)
    remote_site = _site(session, payload.remote)
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
            f"{proposal.outcome.value}: heads do not hold the same transcription "
            f"({proposal.significance.value if proposal.significance else 'unknown'}). "
            "Reconcile the two sides first, or pass force to assert it anyway.",
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
    local_family: str,
    local_code: str,
    local_title: str,
    remote_family: str,
    remote_code: str,
    remote_title: str | None = None,
    session: Session = Depends(get_session),
) -> LadderOut:
    """The ladder for one page pair, and whether its anchor is still current.

    Query parameters rather than a body: this is a read, and it should be
    reachable by pasting a URL.
    """
    local_site = _site(session, SiteRef(family=local_family, code=local_code))
    remote_site = _site(session, SiteRef(family=remote_family, code=remote_code))
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
