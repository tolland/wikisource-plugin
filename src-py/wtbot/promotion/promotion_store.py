import re

from sqlmodel import Session, select

from wtbot.content_model import ProofreadPageDocument, parse_document
from wtbot.fetch.revision_store import head_revision
from wtbot.linking.page_link_store import find_pair
from wtbot.linking.remote_link_store import assert_link, current_anchor, ladder
from wtbot.matching import content_of
from wtbot.model import (
    MAIN_SLOT,
    BatchStatus,
    Content,
    LinkOrigin,
    Page,
    Promotion,
    PromotionBatch,
    PromotionIntent,
    PromotionStatus,
    Revision,
    RevisionLink,
    Site,
    SiteCredential,
    Slot,
)
from wtbot.sync import SyncPage, SyncReport, SyncVerdict

"""Staging a push run from a sync report, one source revision at a time.

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

**One revision at a time.** Each source revision after the asserted anchor is
frozen as its own ordered promotion. That preserves both its edit summary and
the one-to-one correspondence ladder when it is replayed on the target.
"""

_SEMVER = (
    r"(?:0|[1-9]\d*)\."
    r"(?:0|[1-9]\d*)\."
    r"(?:0|[1-9]\d*)"
    r"(?:-(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?:[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)
_PYWIKIBOT_DEFAULT_COMMENT = re.compile(rf"Pywikibot {_SEMVER}")


class PromotionError(ValueError):
    """A batch or promotion that cannot be staged or run as asked."""


def stage_batch(
    session: Session,
    report: SyncReport,
    *,
    source_site: Site,
    target_site: Site,
    label: str | None = None,
    page_number: int,
) -> PromotionBatch:
    """Build one page batch from the selected row of a work report."""
    if report.blocked:
        raise PromotionError("the report is blocked: " + "; ".join(report.blockers))

    wanted = [page for page in report.pages if page.page_number == page_number]
    if len(wanted) != 1:
        raise PromotionError(f"page {page_number} is not unique in this work report")
    return stage_page(
        session,
        wanted[0],
        source_site=source_site,
        target_site=target_site,
        label=label,
        index_link_pk=report.work_pk,
    )


def stage_page(
    session: Session,
    page: SyncPage,
    *,
    source_site: Site,
    target_site: Site,
    label: str | None = None,
    index_link_pk: int | None = None,
    limit: int | None = None,
) -> PromotionBatch:
    """Stage a single-page push run: this page, this direction, nothing else.

    The ``sync-page`` counterpart of :func:`stage_batch`, with no page fan-out.
    It may hold several ordered promotions when several source revisions lie
    between the asserted anchor and the source head.
    """
    if not page.actionable:
        if page.verdict is SyncVerdict.unlinked:
            raise PromotionError(
                f"{page.source_title} needs linking first; staging cannot infer "
                "page correspondence from a comparison"
            )
        raise PromotionError(
            f"{page.source_title} is not writable in this direction "
            f"({page.verdict.value}); a push replays onto an asserted anchor "
            "and cannot invent one"
        )

    source_page = session.exec(
        select(Page).where(
            Page.site_pk == source_site.pk, Page.title == page.source_title
        )
    ).one()
    target_page = (
        session.exec(
            select(Page).where(
                Page.site_pk == target_site.pk, Page.title == page.target_title
            )
        ).first()
        if page.target_title
        else None
    )
    pairing = (
        find_pair(session, source_page.pk, target_page.pk)
        if target_page is not None
        else None
    )
    batch = PromotionBatch(
        source_site_pk=source_site.pk,
        target_site_pk=target_site.pk,
        index_link_pk=index_link_pk,
        page_link_pk=pairing.pk if pairing else None,
        source_page_pk=source_page.pk,
        target_page_pk=target_page.pk if target_page else None,
        source_title=page.source_title or "",
        target_title=page.target_title or page.source_title or "",
        page_number=page.page_number,
        label=label,
    )
    session.add(batch)
    session.flush()

    _stage_promotions_for(session, batch, page, source_site, target_site, limit=limit)
    session.flush()
    return batch


def stage_next_change(
    session: Session,
    page: SyncPage,
    *,
    source_site: Site,
    target_site: Site,
) -> Promotion:
    """Freeze only the oldest source revision beyond the current anchor."""
    if not page.actionable:
        raise PromotionError(
            f"{page.source_title} has no next writable change ({page.verdict.value})"
        )
    batch = stage_page(
        session,
        page,
        source_site=source_site,
        target_site=target_site,
        label="single-change",
        limit=1,
    )
    return promotions(session, batch.pk)[0]


def _stage_promotions_for(
    session: Session,
    batch: PromotionBatch,
    page: SyncPage,
    source_site: Site,
    target_site: Site,
    *,
    limit: int | None = None,
) -> list[Promotion]:
    source_page = session.get(Page, batch.source_page_pk)
    source_head = head_revision(session, source_page)
    if source_head is None:  # pragma: no cover - actionable implies a head
        raise PromotionError(f"{page.source_title} has no cached revision to push")

    target_page = (
        session.get(Page, batch.target_page_pk)
        if batch.target_page_pk is not None
        else None
    )

    intent = (
        PromotionIntent.create
        if page.verdict is SyncVerdict.create
        else PromotionIntent.update
    )
    anchor_pk = None
    source_anchor: Revision | None = None
    base_revid = None
    if intent is PromotionIntent.update:
        if target_page is None:  # pragma: no cover - a push verdict implies one
            raise PromotionError(
                f"{page.source_title} is staged as an update with no target page"
            )
        rungs = ladder(session, page_pk=source_page.pk, other_page_pk=target_page.pk)
        if not rungs:  # pragma: no cover - a push verdict implies a ladder
            raise PromotionError(
                f"{page.source_title} is staged as an update with no asserted "
                "anchor; a push replays onto the anchor and cannot invent one"
            )
        anchor = current_anchor(
            session, page_pk=source_page.pk, other_page_pk=target_page.pk
        )
        if anchor is None:  # pragma: no cover - rungs is non-empty
            raise PromotionError(f"{page.source_title} has no current anchor")
        anchor_pk = anchor.pk
        source_anchor = _revision_on_page(session, anchor, source_page)
        target_head = head_revision(session, target_page)
        base_revid = target_head.revid if target_head else None
    batch.source_head_revid = source_head.revid
    batch.anchor_link_pk = anchor_pk
    session.add(batch)
    revisions = _revisions_after_anchor(
        session, source_page, source_head, source_anchor
    )
    if not revisions:
        raise PromotionError(
            f"{page.source_title} has no source revisions after its current anchor"
        )

    rows: list[Promotion] = []
    predecessor: Promotion | None = None
    for revision in revisions[:limit]:
        row = Promotion(
            batch_pk=batch.pk,
            intent=(intent if predecessor is None else PromotionIntent.update),
            source_revision_pk=revision.pk,
            predecessor_promotion_pk=predecessor.pk if predecessor else None,
            base_revid=base_revid if predecessor is None else None,
            body=promoted_body(session, revision, source_site, target_site),
            comment=_promotion_comment(revision),
        )
        session.add(row)
        session.flush()
        rows.append(row)
        predecessor = row
    return rows


def _revision_on_page(session: Session, link: RevisionLink, page: Page) -> Revision:
    """Return the side of a rung belonging to ``page``."""
    for revision_pk in (link.local_revision_pk, link.remote_revision_pk):
        revision = session.get(Revision, revision_pk)
        if revision is not None and revision.page_pk == page.pk:
            return revision
    raise PromotionError(f"anchor {link.pk} does not belong to {page.title}")


def _revisions_after_anchor(
    session: Session,
    page: Page,
    head: Revision,
    anchor: Revision | None,
) -> list[Revision]:
    """The complete cached ancestry after ``anchor``, oldest first.

    Refusing a gap is essential: treating the oldest revision we happen to
    hold as the next step would silently squash the missing source edits -- the
    exact loss this queue exists to prevent.
    """
    reverse: list[Revision] = []
    current = head
    while anchor is None or current.pk != anchor.pk:
        reverse.append(current)
        if current.parent_revid in (None, 0):
            if anchor is not None:
                raise PromotionError(
                    f"cached history for {page.title} reaches its root before "
                    f"anchor revid {anchor.revid}"
                )
            break
        parent = session.exec(
            select(Revision).where(
                Revision.page_pk == page.pk,
                Revision.revid == current.parent_revid,
            )
        ).first()
        if parent is None:
            destination = (
                f"anchor revid {anchor.revid}" if anchor is not None else "the root"
            )
            raise PromotionError(
                f"cached history for {page.title} is missing parent revid "
                f"{current.parent_revid}; fetch history through {destination} "
                "before staging so revisions are not squashed"
            )
        current = parent
    return list(reversed(reverse))


def _promotion_comment(revision: Revision) -> str:
    """Preserve real summaries, but discard Pywikibot's version-only default."""
    comment = revision.comment or ""
    if _PYWIKIBOT_DEFAULT_COMMENT.fullmatch(comment.strip()):
        return ""
    return comment


def promoted_body(
    session: Session,
    source_revision: Revision,
    source_site: Site,
    target_site: Site,
) -> str:
    """The source body as it would be written to the target.

    The MVP transformation maps only the configured account used by this tool:
    when ``pagequality user=`` names the source site's credential username, it
    is replaced by the target site's credential username. Empty and unknown
    users are preserved exactly. This is deliberately conservative: the tag is
    serialized content, not a foreign key to a wiki account, so an unconfigured
    name carries no evidence that it should be translated (discussion §7).

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
    if not isinstance(document, ProofreadPageDocument):
        return content.text
    source_credential = session.get(SiteCredential, source_site.pk)
    if source_credential is None or document.user != source_credential.username:
        return content.text

    target_credential = _push_credential(session, target_site)
    if target_credential.username == source_credential.username:
        return content.text
    return document.with_user(target_credential.username).serialize()


def _push_credential(session: Session, target_site: Site) -> SiteCredential:
    credential = session.get(SiteCredential, target_site.pk)
    if credential is None:
        raise PromotionError(
            f"no credential for {target_site.label or target_site.family}: a "
            "mapped pagequality user needs a target account"
        )
    return credential


def promotions(session: Session, batch_pk: int) -> list[Promotion]:
    rows = list(
        session.exec(select(Promotion).where(Promotion.batch_pk == batch_pk)).all()
    )
    rows.sort(key=lambda row: row.pk or 0)
    return rows


def next_staged(session: Session, batch_pk: int) -> Promotion | None:
    """The next source revision to push, in ancestry order."""
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
    """Drop this revision and its dependent steps without abandoning the run."""
    if promotion.status is not PromotionStatus.staged:
        raise PromotionError(
            f"promotion {promotion.pk} is {promotion.status.value}; only a "
            "staged row can be skipped"
        )
    current: Promotion | None = promotion
    while current is not None:
        current.status = PromotionStatus.skipped
        session.add(current)
        current = session.exec(
            select(Promotion).where(
                Promotion.predecessor_promotion_pk == current.pk,
                Promotion.status == PromotionStatus.staged,
            )
        ).first()
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
    batch = session.get(PromotionBatch, promotion.batch_pk)
    source_page = session.get(Page, batch.source_page_pk)
    head = head_revision(session, source_page)
    if batch.source_head_revid is not None:
        return head is not None and head.revid == batch.source_head_revid
    staged = list(
        session.exec(
            select(Promotion).where(Promotion.batch_pk == promotion.batch_pk)
        ).all()
    )
    staged.sort(key=lambda row: row.pk or 0)
    return (
        bool(staged) and head is not None and head.pk == staged[-1].source_revision_pk
    )


def target_head_revid(session: Session, promotion: Promotion) -> int | None:
    if promotion.predecessor_promotion_pk is not None:
        predecessor = session.get(Promotion, promotion.predecessor_promotion_pk)
        return predecessor.result_revid if predecessor is not None else None
    batch = session.get(PromotionBatch, promotion.batch_pk)
    target = (
        session.get(Page, batch.target_page_pk)
        if batch.target_page_pk is not None
        else None
    )
    if target is None:
        target = session.exec(
            select(Page).where(
                Page.site_pk == batch.target_site_pk,
                Page.title == batch.target_title,
            )
        ).first()
    head = head_revision(session, target) if target else None
    return head.revid if head else None


def body_matches_target(session: Session, promotion: Promotion) -> bool:
    """Whether the target already holds what we would write.

    Cheap and worth doing: a page pushed by somebody else in the meantime, or
    re-staged twice, otherwise costs a null edit -- which is a revision on
    somebody's watchlist for nothing.
    """
    # The cached target head is deliberately stale between steps in a chain;
    # the preceding save result, not this row, describes its actual head.
    if promotion.predecessor_promotion_pk is not None:
        return False
    batch = session.get(PromotionBatch, promotion.batch_pk)
    target = (
        session.get(Page, batch.target_page_pk)
        if batch.target_page_pk is not None
        else None
    )
    if target is None:
        target = session.exec(
            select(Page).where(
                Page.site_pk == batch.target_site_pk,
                Page.title == batch.target_title,
            )
        ).first()
    head = head_revision(session, target) if target else None
    if head is None:
        return False
    content = content_of(session, head)
    return content is not None and content.text == promotion.body


def materialize_promotion_links(
    session: Session, target_page: Page
) -> list[RevisionLink]:
    """Turn fetched promotion results into their exact one-to-one ladder rungs.

    A save response identifies the new target revision by revid, but the fetch
    worker owns Revision rows. Once it has made those rows concrete, this joins
    each one back to the source revision frozen on the corresponding promotion.
    No content heuristic or head-only proposal is involved.
    """
    if target_page.pk is None:
        return []
    rows = session.exec(
        select(Promotion)
        .join(PromotionBatch, Promotion.batch_pk == PromotionBatch.pk)
        .where(
            PromotionBatch.target_site_pk == target_page.site_pk,
            PromotionBatch.target_title == target_page.title,
            Promotion.status == PromotionStatus.pushed,
            Promotion.result_revid.is_not(None),
        )
        .order_by(Promotion.pk)
    ).all()
    linked: list[RevisionLink] = []
    for promotion in rows:
        batch = session.get(PromotionBatch, promotion.batch_pk)
        target_revision = session.exec(
            select(Revision).where(
                Revision.page_pk == target_page.pk,
                Revision.revid == promotion.result_revid,
            )
        ).first()
        if target_revision is None:
            continue
        link = assert_link(
            session,
            local_revision_pk=promotion.source_revision_pk,
            remote_revision_pk=target_revision.pk,
            origin=LinkOrigin.copy,
            page_link_pk=batch.page_link_pk,
        )
        batch.target_page_pk = target_page.pk
        batch.page_link_pk = link.page_link_pk
        session.add(batch)
        linked.append(link)
    return linked
