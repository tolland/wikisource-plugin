from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlmodel import Session, select

from wtbot.api.debug_logging_route import DebugLoggingRoute
from wtbot.api.links import ProposalOut
from wtbot.api.links import _out as proposal_out
from wtbot.api.sync import BatchOut, SyncPageOut, _batch_out, _page_out
from wtbot.deps import get_session
from wtbot.linking.page_link_store import pair_pages
from wtbot.matching import LinkProposal, compare_pages, confirm_proposals
from wtbot.model import (
    FetchKind,
    FetchRequest,
    LinkOrigin,
    Page,
    PageLink,
    PageTreeLink,
    PromotionBatch,
    Site,
    Title,
)
from wtbot.page_tree import TreeMember, members, report_member
from wtbot.promotion.promotion_store import PromotionError, stage_page
from wtbot.site_store import require_credentialed_site, resolve_pair
from wtbot.title_store import canonical_spelling, ensure_title

router = APIRouter(
    prefix="/links/trees", tags=["page trees"], route_class=DebugLoggingRoute
)


class TreeRequest(BaseModel):
    source_label: str
    target_label: str
    source_root: str = Field(min_length=1)
    target_root: str = Field(min_length=1)

    @field_validator("source_root", "target_root")
    @classmethod
    def root_title(cls, value: str) -> str:
        value = canonical_spelling(value.strip())
        if not value or value.endswith("/") or "://" in value:
            raise ValueError(
                "Enter a page title without a trailing slash, rather than a URL"
            )
        return value


class TreeSummary(TreeRequest):
    pk: int


class TreeDirection(BaseModel):
    reverse: bool = False


class TreeSelection(TreeDirection):
    source_titles: list[str] = Field(min_length=1)


class TreeFetch(TreeDirection):
    revisions: int = Field(default=50, ge=1, le=1000)


class TreeRow(BaseModel):
    path: str
    page: SyncPageOut
    proposal: ProposalOut | None = None


class TreeReport(BaseModel):
    tree: TreeSummary
    rows: list[TreeRow]
    note: str = (
        "Cached root and slash-delimited descendants only. Fetch both trees and mapped "
        "counterparts before reviewing. Page bodies are copied as stored; absolute wiki "
        "links, templates and transclusion titles are not rewritten."
    )


def _ends(
    session: Session, pk: int, reverse: bool = False
) -> tuple[Title, Title, Site, Site]:
    tree = session.get(PageTreeLink, pk)
    pair = session.get(PageLink, pk) if tree else None
    if pair is None:
        raise HTTPException(404, "page tree mapping not found")
    source = session.get(Title, pair.remote_page_pk if reverse else pair.local_page_pk)
    target = session.get(Title, pair.local_page_pk if reverse else pair.remote_page_pk)
    return (
        source,
        target,
        session.get(Site, source.site_pk),
        session.get(Site, target.site_pk),
    )


def _summary(session: Session, pk: int, reverse: bool = False) -> TreeSummary:
    source, target, source_site, target_site = _ends(session, pk, reverse)
    return TreeSummary(
        pk=pk,
        source_label=source_site.label,
        target_label=target_site.label,
        source_root=source.title,
        target_root=target.title,
    )


@router.get("", response_model=list[TreeSummary])
def list_trees(session: Session = Depends(get_session)) -> list[TreeSummary]:
    return [
        _summary(session, tree.pk) for tree in session.exec(select(PageTreeLink)).all()
    ]


@router.post("", response_model=TreeSummary, status_code=201)
def create_tree(
    payload: TreeRequest, session: Session = Depends(get_session)
) -> TreeSummary:
    source_site, target_site = resolve_pair(
        session, payload.source_label, payload.target_label
    )
    if source_site.pk == target_site.pk:
        raise HTTPException(422, "Choose two different sites")
    source = ensure_title(
        session,
        site_pk=source_site.pk,
        title=payload.source_root,
        expected_content_model="wikitext",
    )
    target = ensure_title(
        session,
        site_pk=target_site.pk,
        title=payload.target_root,
        expected_content_model="wikitext",
    )
    pair = pair_pages(session, source, target, origin=LinkOrigin.manual)
    if session.get(PageTreeLink, pair.pk) is None:
        session.add(PageTreeLink(pk=pair.pk))
    session.commit()
    return _summary(session, pair.pk)


@router.post("/{pk}/report", response_model=TreeReport)
def tree_report(
    pk: int, payload: TreeDirection, session: Session = Depends(get_session)
) -> TreeReport:
    source, target, source_site, target_site = _ends(session, pk, payload.reverse)
    rows: list[TreeRow] = []
    for member in members(
        session, source_site, target_site, source.title, target.title
    ):
        page = report_member(session, member, source_site, target_site)
        if page is None:
            continue
        proposal = None
        if member.source and member.target:
            source_page = session.get(Page, member.source.pk)
            target_page = session.get(Page, member.target.pk)
            if source_page and target_page:
                proposal = proposal_out(
                    compare_pages(session, source_page, target_page)
                )
        rows.append(TreeRow(path=member.path, page=_page_out(page), proposal=proposal))
    return TreeReport(tree=_summary(session, pk, payload.reverse), rows=rows)


@router.post("/{pk}/pairs")
def pair_tree(
    pk: int, payload: TreeSelection, session: Session = Depends(get_session)
) -> dict[str, int]:
    source, target, source_site, target_site = _ends(session, pk, payload.reverse)
    selected = _selection(
        session, source_site, target_site, source, target, payload.source_titles
    )
    for member in selected:
        local = member.source or ensure_title(
            session,
            site_pk=source_site.pk,
            title=member.source_title,
            expected_content_model="wikitext",
        )
        remote = member.target or ensure_title(
            session,
            site_pk=target_site.pk,
            title=member.target_title,
            expected_content_model=local.expected_content_model,
        )
        pair_pages(session, local, remote, origin=LinkOrigin.manual)
    session.commit()
    return {"paired": len(selected)}


def _selection(
    session: Session,
    source_site: Site,
    target_site: Site,
    source: Title,
    target: Title,
    titles: list[str],
) -> list[TreeMember]:
    available = {
        m.source_title: m
        for m in members(session, source_site, target_site, source.title, target.title)
    }
    names = list(dict.fromkeys(map(canonical_spelling, titles)))
    if any(name not in available for name in names):
        raise HTTPException(422, "Selection includes a title outside this page tree")
    return [available[name] for name in names]


@router.post("/{pk}/confirm")
def confirm_tree(
    pk: int, payload: TreeSelection, session: Session = Depends(get_session)
) -> dict[str, int]:
    source, target, source_site, target_site = _ends(session, pk, payload.reverse)
    selected = _selection(
        session, source_site, target_site, source, target, payload.source_titles
    )
    proposals: list[LinkProposal] = []
    for member in selected:
        source_page = session.get(Page, member.source.pk) if member.source else None
        target_page = session.get(Page, member.target.pk) if member.target else None
        if source_page is None or target_page is None:
            raise HTTPException(
                409, f"{member.source_title}: fetch both pages before linking revisions"
            )
        proposal = compare_pages(session, source_page, target_page)
        if not proposal.proposable:
            raise HTTPException(
                409, f"{member.source_title}: no matching revision anchor"
            )
        proposals.append(proposal)
    confirmed = confirm_proposals(session, proposals)
    session.commit()
    return {"confirmed": len(confirmed)}


@router.post("/{pk}/fetch")
def fetch_tree(
    pk: int, payload: TreeFetch, session: Session = Depends(get_session)
) -> dict[str, int]:
    source, target, source_site, target_site = _ends(session, pk, payload.reverse)
    # Validate both before writing any queue entries.
    for site in (source_site, target_site):
        require_credentialed_site(session, site.label)
    queued = {(source_site.pk, source.title): 1, (target_site.pk, target.title): 1}
    for member in members(
        session, source_site, target_site, source.title, target.title
    ):
        queued.setdefault((source_site.pk, member.source_title), 0)
        queued.setdefault((target_site.pk, member.target_title), 0)
    for (site_pk, title), depth in queued.items():
        session.add(
            FetchRequest(
                site_pk=site_pk,
                title=title,
                kind=FetchKind.single,
                depth=depth,
                revisions=payload.revisions,
            )
        )
    session.commit()
    return {"queued": len(queued)}


@router.post("/{pk}/batches", response_model=list[BatchOut], status_code=201)
def stage_tree(
    pk: int, payload: TreeSelection, session: Session = Depends(get_session)
) -> list[BatchOut]:
    source, target, source_site, target_site = _ends(session, pk, payload.reverse)
    selected = _selection(
        session, source_site, target_site, source, target, payload.source_titles
    )
    batches: list[PromotionBatch] = []
    try:
        for member in selected:
            page = report_member(session, member, source_site, target_site)
            if page is None:
                raise PromotionError(f"{member.source_title}: no revisions to stage")
            batches.append(
                stage_page(
                    session, page, source_site=source_site, target_site=target_site
                )
            )
    except PromotionError as exc:
        session.rollback()
        raise HTTPException(409, str(exc)) from exc
    session.commit()
    return [_batch_out(session, batch, include_bodies=True) for batch in batches]
