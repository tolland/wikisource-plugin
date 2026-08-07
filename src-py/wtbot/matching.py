from dataclasses import dataclass
from enum import Enum

from sqlalchemy import func
from sqlmodel import Session, select

from wtbot.content_model import Significance, parse_document
from wtbot.model import LinkOrigin, NsRole, Page, PageMeta, RemoteLink, Site
from wtbot.remote_link_store import assert_link, find_link
from wtbot.revision_store import head_content, head_revision
from wtbot.vfs.store import canonical_title

"""Proposing correspondences between two sites' copies of a work.

**Proposals only.** Nothing here writes a ``RemoteLink``; ``confirm_proposals``
does, and only for pairs a caller has named. Item 5 of the sync TODO is explicit
that proposals are proposals -- the whole reason correspondence is asserted
rather than computed is that no comparison is authoritative enough to act on
unreviewed.

Two decisions worth stating, because both look like they should go the other
way:

**Only heads are compared.** Not "find the revision in their history matching
ours" -- that question has no single answer. Null and touch edits create runs of
byte-identical revisions (four in the Canadian patent fixture, and en.wikisource
ran a whole `Pywikibot touch edit` campaign in 2018), so a content match can
land on any member of a run with nothing to choose between them. It is also a
question the design already declined: remote history is append-only, there is no
rebase and no merge base to discover, so the anchor is recorded when a page is
pulled and re-established by hand when it breaks (discussion section 2). And our
revision store is *sparse* -- we hold the revisions we happened to fetch -- so a
history walk would be bounded by our sampling rather than by the wiki's history.
Heads have exactly one revision per side and no ambiguity.

Were a historical base ever needed, the rule would be *the newest revision of a
content-equal run*: every member is an equally true claim, so the newest is the
tightest one, and an older anchor makes a page look diverged when it is not.

**"Same content" is not byte equality.** A ``proofread-page`` body carries
``pagequality user=``, which names an account on one wiki, so the same
transcription routinely differs across sites -- that is the norm, not an
exception. Sameness is decided by the content-model comparison, and the
proofreading *level* is treated as significant because it is directional:
equal words do not make it safe to overwrite someone's assessment.
"""


class MatchOutcome(str, Enum):
    """Why a page pair can or cannot be linked.

    Deliberately not a boolean plus a message: the ways a pairing fails need
    different actions, and collapsing them loses which.
    """

    same = "same"
    """Heads hold the same transcription. Proposable."""

    quality_differs = "quality_differs"
    """Same transcription, different proofreading level. Proposable, but the
    level is directional -- pushing 2 over someone's 4 discards an assessment
    -- so it is surfaced rather than folded in with ``same``."""

    diverged = "diverged"
    """The transcriptions differ. Not a link: discussion section 2's forward
    re-anchoring wants a human to make the two sides identical first."""

    no_counterpart = "no_counterpart"
    """Nothing on the other site holds this page. A redlink has no link, which
    is correct -- there is nothing to compare."""

    unfetched = "unfetched"
    """One side has no head revision cached, so there is nothing to compare
    yet. A fetch, not a verdict."""

    already_linked = "already_linked"
    """The pair already has a link. Re-asserting would be a no-op, so it is
    reported rather than proposed again."""


PROPOSABLE = (MatchOutcome.same, MatchOutcome.quality_differs)


@dataclass(frozen=True)
class LinkProposal:
    """One page pair and what comparing their heads said."""

    outcome: MatchOutcome
    local_title: str
    page_number: int | None = None
    remote_title: str | None = None
    local_revision_pk: int | None = None
    remote_revision_pk: int | None = None
    local_revid: int | None = None
    remote_revid: int | None = None
    significance: Significance | None = None
    detail: str | None = None

    @property
    def proposable(self) -> bool:
        return self.outcome in PROPOSABLE


def propose_index_links(
    session: Session,
    *,
    local_site: Site,
    remote_site: Site,
    local_index_title: str,
    remote_index_title: str | None = None,
) -> list[LinkProposal]:
    """Pair up two indexes' Page: children and compare each pair's heads.

    Pages are matched on **page number within the index**, not on title text:
    ``--to`` exists precisely because the two sides' titles can differ, and the
    scan offset is the thing that actually has to line up (discussion section
    6). Namespace roles are read from the rows, never numeric ids, which differ
    between installs.
    """
    remote_index_title = remote_index_title or local_index_title

    local_pages = _index_children(session, local_site, local_index_title)
    remote_pages = _index_children(session, remote_site, remote_index_title)
    remote_by_number = {
        number: page for number, page in remote_pages if number is not None
    }
    remote_by_title = {canonical_title(page.title): page for _, page in remote_pages}

    proposals: list[LinkProposal] = []
    for number, local_page in sorted(
        local_pages, key=lambda pair: (pair[0] is None, pair[0] or 0)
    ):
        remote_page = remote_by_number.get(number) if number is not None else None
        if remote_page is None:
            # Fall back to the title only when the structural key is missing:
            # a page number that lines up is a stronger claim than a string
            # that happens to match.
            remote_page = remote_by_title.get(canonical_title(local_page.title))
        proposals.append(
            compare_pages(session, local_page, remote_page, page_number=number)
        )
    return proposals


def compare_pages(
    session: Session,
    local_page: Page,
    remote_page: Page | None,
    *,
    page_number: int | None = None,
) -> LinkProposal:
    """Compare one page pair's head revisions."""
    base = {"local_title": local_page.title, "page_number": page_number}

    if remote_page is None:
        return LinkProposal(outcome=MatchOutcome.no_counterpart, **base)

    base["remote_title"] = remote_page.title

    local_revision = head_revision(session, local_page)
    remote_revision = head_revision(session, remote_page)
    if local_revision is None or remote_revision is None:
        missing = "local" if local_revision is None else "remote"
        return LinkProposal(
            outcome=MatchOutcome.unfetched,
            detail=f"{missing} side has no cached head revision",
            **base,
        )

    base |= {
        "local_revision_pk": local_revision.pk,
        "remote_revision_pk": remote_revision.pk,
        "local_revid": local_revision.revid,
        "remote_revid": remote_revision.revid,
    }

    existing = find_link(
        session,
        revision_pk=local_revision.pk,
        other_revision_pk=remote_revision.pk,
    )
    if existing is not None:
        return LinkProposal(
            outcome=MatchOutcome.already_linked,
            detail=f"link #{existing.pk}, origin {existing.origin.value}",
            **base,
        )

    local_content = head_content(session, local_page)
    remote_content = head_content(session, remote_page)
    if local_content is None or remote_content is None:
        return LinkProposal(
            outcome=MatchOutcome.unfetched,
            detail="a head revision has no main slot content",
            **base,
        )

    comparison = parse_document(
        local_content.text, local_content.content_model
    ).compare(parse_document(remote_content.text, remote_content.content_model))

    if not comparison.same_transcription:
        return LinkProposal(
            outcome=MatchOutcome.diverged,
            significance=comparison.significance,
            **base,
        )
    outcome = (
        MatchOutcome.quality_differs
        if comparison.significance is Significance.metadata_significant
        else MatchOutcome.same
    )
    return LinkProposal(outcome=outcome, significance=comparison.significance, **base)


def confirm_proposals(
    session: Session,
    proposals: list[LinkProposal],
    *,
    origin: LinkOrigin = LinkOrigin.title_match,
) -> list[RemoteLink]:
    """Write links for the proposals given -- and only those.

    The caller decides what to pass; nothing here filters on the caller's
    behalf, because "confirm everything that looked fine" is exactly the
    auto-confirmation the design rules out. A non-proposable proposal is a
    programming error rather than something to skip silently.
    """
    links = []
    for proposal in proposals:
        if not proposal.proposable:
            raise ValueError(
                f"{proposal.local_title} is {proposal.outcome.value}, not proposable"
            )
        links.append(
            assert_link(
                session,
                local_revision_pk=proposal.local_revision_pk,
                remote_revision_pk=proposal.remote_revision_pk,
                origin=origin,
            )
        )
    return links


def _index_children(
    session: Session, site: Site, index_title: str
) -> list[tuple[int | None, Page]]:
    """A work's Page: rows with their page numbers.

    Membership comes from ``PageMeta.index_title`` rather than a title prefix,
    and is compared with underscores normalised to spaces -- MediaWiki treats
    the two as equivalent, and a fetched page keeps the wiki's spelling while a
    fan-out stub keeps the request's (see wtbot.vfs.store.canonical_title).
    """
    rows = session.exec(
        select(PageMeta.page_number, Page)
        .join(Page, Page.pk == PageMeta.page_pk)
        .where(
            Page.site_pk == site.pk,
            Page.namespace_role == NsRole.page,
            func.replace(PageMeta.index_title, "_", " ")
            == canonical_title(index_title),
        )
    ).all()
    return [(number, page) for number, page in rows]
