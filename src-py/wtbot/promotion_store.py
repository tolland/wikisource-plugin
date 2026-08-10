from sqlmodel import Session, select

from wtbot.content_model import parse_document
from wtbot.matching import content_of
from wtbot.model import (
    MAIN_SLOT,
    BatchStatus,
    Content,
    Page,
    Promotion,
    PromotionBatch,
    PromotionIntent,
    PromotionStatus,
    Revision,
    Site,
    Slot,
)
from wtbot.page_link_store import find_pair
from wtbot.remote_link_store import ladder
from wtbot.revision_store import head_revision
from wtbot.sync import SyncReport, SyncVerdict
from wtbot.timeutil import utcnow

"""Staging a push run from a sync report, and pushing it one page at a time.

**Staging freezes the report.** A sync report is recomputed on every load, and
should be -- it describes revisions currently held. But a queued push must not
change meaning between review and execution, so the body, the base revid and
the anchor are copied in here and re-checked at push time. What was approved is
what is sent.

**Only what the report calls actionable.** A `push` has an asserted anchor to
replay onto, and a `create` has nothing on the target to replay onto at all.
Everything else -- an unlinked page a comparison likes, a diverged pair, a page
the target is ahead on -- is refused rather than staged, because staging is the
last point at which "we are not sure these correspond" is cheap to say.

**One page at a time.** `push_one` is the unit, because a rate-limited wiki and
a reviewer both want it that way: the run can be watched, paused and abandoned
between pages, and a batch that half-succeeds is an ordinary end state rather
than a failure to unpick.
"""


class PromotionError(ValueError):
    """A batch or promotion that cannot be staged or run as asked."""


def stage_batch(
    session: Session,
    report: SyncReport,
    *,
    source_site: Site,
    target_site: Site,
    label: str | None = None,
    page_numbers: list[int] | None = None,
) -> PromotionBatch:
    """Build a draft batch from a report's actionable rows.

    ``page_numbers`` narrows it to a chosen subset -- the usual case, because a
    reviewer works down a list and stages what they have actually looked at.
    """
    if report.blocked:
        raise PromotionError("the report is blocked: " + "; ".join(report.blockers))

    wanted = [page for page in report.pages if page.actionable]
    if page_numbers is not None:
        chosen = set(page_numbers)
        wanted = [page for page in wanted if page.page_number in chosen]
    if not wanted:
        raise PromotionError(
            "nothing to stage: no page in this report is writable in this "
            "direction. An unlinked page needs linking first."
        )

    batch = PromotionBatch(
        source_site_pk=source_site.pk,
        target_site_pk=target_site.pk,
        index_link_pk=report.work_pk,
        source_index_title=report.source.index_title,
        target_index_title=report.target.index_title,
        label=label,
    )
    session.add(batch)
    session.flush()

    for page in wanted:
        session.add(_promotion_for(session, batch, page, source_site, target_site))
    session.flush()
    return batch


def _promotion_for(
    session: Session,
    batch: PromotionBatch,
    page,
    source_site: Site,
    target_site: Site,
) -> Promotion:
    source_page = session.exec(
        select(Page).where(
            Page.site_pk == source_site.pk, Page.title == page.source_title
        )
    ).one()
    source_head = head_revision(session, source_page)
    if source_head is None:  # pragma: no cover - actionable implies a head
        raise PromotionError(f"{page.source_title} has no cached revision to push")

    target_page = (
        session.exec(
            select(Page).where(
                Page.site_pk == target_site.pk, Page.title == page.target_title
            )
        ).first()
        if page.target_title
        else None
    )

    intent = (
        PromotionIntent.create
        if page.verdict is SyncVerdict.create
        else PromotionIntent.update
    )
    anchor_pk = None
    base_revid = None
    if intent is PromotionIntent.update:
        rungs = ladder(session, page_pk=source_page.pk, other_page_pk=target_page.pk)
        if not rungs:  # pragma: no cover - a push verdict implies a ladder
            raise PromotionError(
                f"{page.source_title} is staged as an update with no asserted "
                "anchor; a push replays onto the anchor and cannot invent one"
            )
        anchor_pk = rungs[-1].pk
        target_head = head_revision(session, target_page)
        base_revid = target_head.revid if target_head else None

    pairing = (
        find_pair(session, source_page.pk, target_page.pk)
        if target_page is not None
        else None
    )
    return Promotion(
        batch_pk=batch.pk,
        page_link_pk=pairing.pk if pairing else None,
        source_page_pk=source_page.pk,
        target_page_pk=target_page.pk if target_page else None,
        target_title=page.target_title or page.source_title,
        page_number=page.page_number,
        intent=intent,
        source_revision_pk=source_head.pk,
        anchor_link_pk=anchor_pk,
        base_revid=base_revid,
        body=promoted_body(session, source_head, target_site),
        comment=(
            f"Sync from {source_site.label or source_site.family}: "
            f"{batch.source_index_title}"
        ),
    )


def promoted_body(
    session: Session, source_revision: Revision, target_site: Site
) -> str:
    """The source body as it would be written to the target.

    One transformation today, and it is not cosmetic: ``pagequality user=``
    names an account on the *source* wiki, and writing it to the target
    attributes a proofreading assessment to a username that may not exist there
    (discussion §7). It is rewritten to the account performing the push.

    The rest of §7's chain -- capping promoted levels at 3, blocking local-only
    templates, local-only `File:` references and absolute staging-host URLs --
    is deliberately not here yet. Each is a named check with its own verdict,
    and bolting them in as inline string edits is how they end up unreviewable.
    """
    slot = session.get(Slot, (source_revision.pk, MAIN_SLOT))
    if slot is None:  # pragma: no cover - a fetched revision always has one
        raise PromotionError("the source revision has no main slot to push")
    content = session.get(Content, slot.content_pk)

    document = parse_document(content.text, content.content_model)
    with_user = getattr(document, "with_user", None)
    if with_user is None:
        return content.text
    account = _push_account(session, target_site)
    return with_user(account).serialize()


def _push_account(session: Session, target_site: Site) -> str:
    from wtbot.model import SiteCredential

    credential = session.exec(
        select(SiteCredential).where(SiteCredential.site_pk == target_site.pk)
    ).first()
    if credential is None:
        raise PromotionError(
            f"no credential for {target_site.label or target_site.family}: a "
            "push needs an account, and the body records which one made the "
            "assessment"
        )
    return credential.username


def approve(session: Session, batch: PromotionBatch, *, approved_by: str) -> None:
    """Sign a draft off. Required before anything runs.

    Stored rather than trusted to the caller having asked, because "did a
    person agree to this" is exactly the fact an audit wants and exactly the
    one a convenient default would erase.
    """
    if batch.status is not BatchStatus.draft:
        raise PromotionError(f"batch {batch.pk} is {batch.status.value}, not a draft")
    if not approved_by.strip():
        raise PromotionError("an approval needs a name")
    batch.status = BatchStatus.approved
    batch.approved_by = approved_by
    batch.approved_at = utcnow()
    session.add(batch)
    session.flush()


def promotions(session: Session, batch_pk: int) -> list[Promotion]:
    rows = list(
        session.exec(select(Promotion).where(Promotion.batch_pk == batch_pk)).all()
    )
    rows.sort(key=lambda row: (row.page_number is None, row.page_number or 0))
    return rows


def next_staged(session: Session, batch_pk: int) -> Promotion | None:
    """The next page to push, in reading order."""
    return next(
        (
            row
            for row in promotions(session, batch_pk)
            if row.status is PromotionStatus.staged
        ),
        None,
    )


def settle_batch(session: Session, batch: PromotionBatch) -> BatchStatus:
    """Recompute a running batch's status from its rows.

    ``partial`` is an end state, not a failure: some rows refused by a wiki is
    the ordinary outcome of a long run, and a status that could not say so
    would make every real batch read as broken.
    """
    rows = promotions(session, batch.pk)
    if any(row.status is PromotionStatus.staged for row in rows):
        batch.status = BatchStatus.running
    elif any(
        row.status in (PromotionStatus.conflict, PromotionStatus.error) for row in rows
    ):
        batch.status = BatchStatus.partial
    else:
        batch.status = BatchStatus.complete
    session.add(batch)
    session.flush()
    return batch.status


def skip(session: Session, promotion: Promotion) -> None:
    """Drop one page from a run without abandoning the run."""
    if promotion.status is not PromotionStatus.staged:
        raise PromotionError(
            f"promotion {promotion.pk} is {promotion.status.value}; only a "
            "staged row can be skipped"
        )
    promotion.status = PromotionStatus.skipped
    session.add(promotion)
    session.flush()


def abort(session: Session, batch: PromotionBatch) -> int:
    """Stop a run. Staged rows are skipped; pushed rows stay pushed.

    There is no undo here, and pretending otherwise would be worse than the
    gap: reversing a push means appending another revision, which is the
    rollback item the TODO keeps separate precisely because it is not free.
    """
    rows = [
        row
        for row in promotions(session, batch.pk)
        if row.status is PromotionStatus.staged
    ]
    for row in rows:
        row.status = PromotionStatus.skipped
        session.add(row)
    batch.status = BatchStatus.aborted
    session.add(batch)
    session.flush()
    return len(rows)


def source_is_unchanged(session: Session, promotion: Promotion) -> bool:
    """Whether the source still holds what was staged.

    Checked at push time as well as staged: a fetch between review and
    execution can move the source head, and pushing the frozen body would then
    write something nobody looked at *and* record a correspondence to a
    revision that is no longer current.
    """
    source_page = session.get(Page, promotion.source_page_pk)
    head = head_revision(session, source_page)
    return head is not None and head.pk == promotion.source_revision_pk


def target_head_revid(session: Session, promotion: Promotion) -> int | None:
    if promotion.target_page_pk is None:
        return None
    target = session.get(Page, promotion.target_page_pk)
    head = head_revision(session, target) if target else None
    return head.revid if head else None


def body_matches_target(session: Session, promotion: Promotion) -> bool:
    """Whether the target already holds what we would write.

    Cheap and worth doing: a page pushed by somebody else in the meantime, or
    re-staged twice, otherwise costs a null edit -- which is a revision on
    somebody's watchlist for nothing.
    """
    if promotion.target_page_pk is None:
        return False
    target = session.get(Page, promotion.target_page_pk)
    head = head_revision(session, target) if target else None
    if head is None:
        return False
    content = content_of(session, head)
    return content is not None and content.text == promotion.body
