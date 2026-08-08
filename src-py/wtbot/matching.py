from dataclasses import dataclass
from enum import Enum

from sqlalchemy import func
from sqlmodel import Session, select

from wtbot.content_model import Significance, parse_document
from wtbot.model import (
    MAIN_SLOT,
    Content,
    LinkOrigin,
    NsRole,
    Page,
    PageMeta,
    RemoteLink,
    Revision,
    Site,
    Slot,
)
from wtbot.remote_link_store import assert_link, find_link
from wtbot.revision_store import head_revision
from wtbot.vfs.store import canonical_title

"""Proposing correspondences between two sites' copies of a work.

**Proposals only.** Nothing here writes a ``RemoteLink``; ``confirm_proposals``
does, and only for pairs a caller has named. Item 5 of the sync TODO is explicit
that proposals are proposals -- the whole reason correspondence is asserted
rather than computed is that no comparison is authoritative enough to act on
unreviewed.

Two decisions worth stating, because both look like they should go the other
way:

**The anchor is searched for in history, not assumed to be the head.** The
common case is not two heads that agree: it is one side imported at some past
revision of the other, with edits since. Hertz page 9 is the shape --- a local
import matching upstream's second-newest revision, with a proofread bump on top
--- and comparing only heads reports "same words, different level" and offers a
link asserting sameness of two revisions that are *not* the same. That link
would also destroy the useful fact, which is that upstream is exactly one edit
ahead of a base we hold.

So each side's head is compared against the other side's stored revisions,
newest first. Where several match --- a run of null or touch edits, four of
them in the Canadian patent fixture --- the **newest** wins: every member is an
equally true claim, so the newest is the tightest, and an older anchor makes a
page look diverged when it is not.

The search is bounded by what the revision store holds, which is deliberately
sparse. ``Page.history_complete_from_revid`` says how far back the run is known
to be contiguous, and a search that reaches that boundary without a match says
``history_exhausted`` rather than ``diverged``: "we did not look far enough" is
not "they disagree", and only one of them is fixed by fetching more.

**"Same content" is not byte equality.** A ``proofread-page`` body carries
``pagequality user=``, which names an account on one wiki, so the same
transcription routinely differs across sites --- that is the norm, not an
exception. Sameness is decided by the content-model comparison, which compares
header, body and footer and treats the proofreading *level* as significant
because it is directional: equal words do not make it safe to overwrite
someone's assessment.
"""


class MatchOutcome(str, Enum):
    """Why a page pair can or cannot be linked.

    Deliberately not a boolean plus a message: the ways a pairing fails need
    different actions, and collapsing them loses which.
    """

    same = "same"
    """Heads hold the same transcription. Proposable."""

    local_ahead = "local_ahead"
    """The remote head matches one of our older revisions: we have edits it
    does not. Proposable -- the matched pair really is the same content, and it
    is the base those edits replay onto."""

    remote_ahead = "remote_ahead"
    """Our head matches one of the remote's older revisions: they have edits we
    do not. Proposable, same reasoning."""

    quality_differs = "quality_differs"
    """Same words at the heads, different proofreading level, and no anchor
    found in the history we hold.

    **Not** proposable: the two revisions are not the same content, and
    asserting they are would both be false and lose the base. It is almost
    always one edit apart -- the level bump -- so the fix is usually to fetch
    more history and let the anchor search find it."""

    diverged = "diverged"
    """Both sides have edits after their common anchor, or the transcriptions
    simply differ. Not a link: discussion section 2's forward re-anchoring wants
    a human to make the two sides identical first."""

    history_exhausted = "history_exhausted"
    """No anchor in the revisions we hold, and we do not hold the full history.
    A fetch, not a verdict -- distinct from ``diverged``, which is one."""

    no_counterpart = "no_counterpart"
    """Nothing on the other site holds this page. A redlink has no link, which
    is correct -- there is nothing to compare."""

    unfetched = "unfetched"
    """One side has no head revision cached, so there is nothing to compare
    yet. A fetch, not a verdict."""

    already_linked = "already_linked"
    """The pair already has a link. Re-asserting would be a no-op, so it is
    reported rather than proposed again."""


PROPOSABLE = (
    MatchOutcome.same,
    MatchOutcome.local_ahead,
    MatchOutcome.remote_ahead,
)
"""Outcomes whose matched revision pair really is the same content.

``quality_differs`` is deliberately absent: it names a pair that differs, and a
link says a pair does not."""


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

    local_ahead_by: int = 0
    """Revisions on our side newer than the anchor -- what would replay out."""
    remote_ahead_by: int = 0
    """Revisions on their side newer than the anchor -- what would replay in."""
    anchor_is_heads: bool = False
    """True when the matched pair is both heads, i.e. nothing to replay."""

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

    anchor = find_anchor(session, local_page, remote_page)
    if anchor is None:
        return LinkProposal(
            outcome=MatchOutcome.unfetched,
            detail="a head revision has no main slot content",
            **base,
        )

    base |= {
        "local_revision_pk": anchor.local_revision.pk,
        "remote_revision_pk": anchor.remote_revision.pk,
        "local_revid": anchor.local_revision.revid,
        "remote_revid": anchor.remote_revision.revid,
        "significance": anchor.significance,
        "local_ahead_by": anchor.local_ahead_by,
        "remote_ahead_by": anchor.remote_ahead_by,
        "anchor_is_heads": anchor.is_heads,
    }

    existing = find_link(
        session,
        revision_pk=anchor.local_revision.pk,
        other_revision_pk=anchor.remote_revision.pk,
    )
    if existing is not None:
        return LinkProposal(
            outcome=MatchOutcome.already_linked,
            detail=f"link #{existing.pk}, origin {existing.origin.value}",
            **base,
        )

    return LinkProposal(outcome=anchor.outcome, detail=anchor.detail, **base)


@dataclass(frozen=True)
class Anchor:
    """The best correspondence found between two pages, and the distance from
    it to each side's head."""

    local_revision: Revision
    remote_revision: Revision
    outcome: MatchOutcome
    significance: Significance | None = None
    local_ahead_by: int = 0
    remote_ahead_by: int = 0
    detail: str | None = None

    @property
    def is_heads(self) -> bool:
        return self.local_ahead_by == 0 and self.remote_ahead_by == 0


def find_anchor(session: Session, local_page: Page, remote_page: Page) -> Anchor | None:
    """The newest revision pair holding the same content, and what came after.

    Each head is compared against the other side's stored revisions, newest
    first. Only one side is searched at a time -- a pair where *both* sides
    moved after the anchor cannot be resolved by a link anyway (that is
    divergence, and discussion section 2 wants a human), so there is nothing to
    gain from searching for a deeper common ancestor.

    Returns None only when there is nothing to compare at all.
    """
    local_head = head_revision(session, local_page)
    remote_head = head_revision(session, remote_page)
    if local_head is None or remote_head is None:
        return None

    local_content = _content_of(session, local_head)
    remote_content = _content_of(session, remote_head)
    if local_content is None or remote_content is None:
        return None

    heads = _compare(local_content, remote_content)
    if heads.same_transcription and heads.significance is not (
        Significance.metadata_significant
    ):
        return Anchor(
            local_revision=local_head,
            remote_revision=remote_head,
            outcome=MatchOutcome.same,
            significance=heads.significance,
        )

    # Our head against their history: they are ahead.
    match = _newest_match(session, local_content, remote_page, remote_head)
    if match is not None:
        revision, significance, ahead_by = match
        return Anchor(
            local_revision=local_head,
            remote_revision=revision,
            outcome=MatchOutcome.remote_ahead,
            significance=significance,
            remote_ahead_by=ahead_by,
            detail=f"{ahead_by} revision(s) upstream of the anchor",
        )

    # Their head against ours: we are ahead.
    match = _newest_match(session, remote_content, local_page, local_head)
    if match is not None:
        revision, significance, ahead_by = match
        return Anchor(
            local_revision=revision,
            remote_revision=remote_head,
            outcome=MatchOutcome.local_ahead,
            significance=significance,
            local_ahead_by=ahead_by,
            detail=f"{ahead_by} revision(s) local of the anchor",
        )

    outcome, detail = _no_match_outcome(session, local_page, remote_page, heads)
    return Anchor(
        local_revision=local_head,
        remote_revision=remote_head,
        outcome=outcome,
        significance=heads.significance,
        detail=detail,
    )


def _no_match_outcome(
    session: Session, local_page: Page, remote_page: Page, heads
) -> tuple[MatchOutcome, str | None]:
    """Nothing matched -- but "they disagree" and "we did not look far enough"
    are different answers, and only one of them is fixed by fetching."""
    if heads.significance is Significance.metadata_significant:
        return (
            MatchOutcome.quality_differs,
            "same words, different level, and no anchor in the history held",
        )

    incomplete = [
        page
        for page in (local_page, remote_page)
        if not _history_is_complete(session, page)
    ]
    if incomplete:
        sides = " and ".join(
            "local" if page is local_page else "remote" for page in incomplete
        )
        return (
            MatchOutcome.history_exhausted,
            f"no anchor in the revisions held; {sides} history is incomplete",
        )
    return MatchOutcome.diverged, None


def _history_is_complete(session: Session, page: Page) -> bool:
    """Whether we hold this page back to its first revision.

    ``history_complete_from_revid`` marks the oldest revid of a contiguous run
    from the head; the run reaches the beginning when that revision has no
    parent.
    """
    marker = page.history_complete_from_revid
    if marker is None:
        return False
    oldest = session.exec(
        select(Revision).where(Revision.page_pk == page.pk, Revision.revid == marker)
    ).first()
    return oldest is not None and oldest.parent_revid is None


def _newest_match(
    session: Session,
    content,
    other_page: Page,
    other_head: Revision,
) -> tuple[Revision, Significance, int] | None:
    """The newest revision of ``other_page`` holding ``content``'s text.

    Newest first, and the first hit wins: a run of touch edits offers several
    equally true answers, and the newest is the tightest -- an older anchor
    would report revisions as unsynced when they carry no change.
    """
    revisions = _revisions_newest_first(session, other_page)
    for offset, revision in enumerate(revisions):
        if revision.pk == other_head.pk:
            continue
        other_content = _content_of(session, revision)
        if other_content is None:
            continue
        comparison = _compare(content, other_content)
        if comparison.same_transcription and comparison.significance is not (
            Significance.metadata_significant
        ):
            return revision, comparison.significance, offset
    return None


def _revisions_newest_first(session: Session, page: Page) -> list[Revision]:
    return list(
        session.exec(
            select(Revision)
            .where(Revision.page_pk == page.pk)
            .order_by(Revision.revid.desc())
        ).all()
    )


def _content_of(session: Session, revision: Revision) -> Content | None:
    slot = session.get(Slot, (revision.pk, MAIN_SLOT))
    return None if slot is None else session.get(Content, slot.content_pk)


def _compare(left: Content, right: Content):
    return parse_document(left.text, left.content_model).compare(
        parse_document(right.text, right.content_model)
    )


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

    The pair written is the *anchor*, which for ``local_ahead``/``remote_ahead``
    is not the head pair -- that is the point: the anchor is the base the
    unsynced revisions replay onto.
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
