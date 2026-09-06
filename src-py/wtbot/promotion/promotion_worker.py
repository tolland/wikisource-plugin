import logging

from sqlmodel import Session, select

from wtbot.db_session import detached_site, read_snapshot, write_batch
from wtbot.model import (
    BatchStatus,
    FetchKind,
    FetchRequest,
    Promotion,
    PromotionBatch,
    PromotionIntent,
    PromotionStatus,
    Site,
)
from wtbot.promotion.promotion_store import (
    PromotionError,
    body_matches_target,
    settle_batch,
    skip,
    source_is_unchanged,
    target_head_revid,
)
from wtbot.timeutil import utcnow
from wtbot.wiki.wiki_types import EditConflict

"""Executing one promotion: the only place this system writes to a target wiki.

**One revision per call, by design.** Several source revisions on one page are
an ordered chain, so each edit summary and correspondence boundary survives on
the target. A reviewer can still watch, pause and abandon between writes.

**Three checks before the write, and each is a different failure:**

- the promotion is still staged and its batch has not ended;
- the source still holds the revision that was staged -- otherwise the frozen
  body is not what anybody reviewed;
- the target still holds the base revid -- which the wiki re-checks itself via
  ``baserevid``, but checking here first turns a network round trip into a row
  update, and gives the conflict a local explanation.

**The push does not invent revision or link rows.** A successful save identifies
its target revision only by revid, while the fetch worker owns concrete
Revision rows. The last step therefore enqueues a history refetch. Once those
revisions are concrete, the fetch worker joins each result revid to the exact
source revision frozen in its promotion and appends the corresponding `copy`
rung.
"""

log = logging.getLogger(__name__)


def push_one(
    session: Session,
    promotion_pk: int,
    client_factory,
    *,
    force: bool = False,
) -> Promotion:
    """Write one staged promotion to its target wiki.

    Returns the promotion with its outcome recorded. Never raises for a wiki
    refusing the edit -- that is a status, and a caller pushing a batch page by
    page needs the next call to be possible.
    """
    with read_snapshot(session):
        promotion = session.get(Promotion, promotion_pk)
        if promotion is None:
            raise PromotionError(f"no promotion {promotion_pk}")
        batch = session.get(PromotionBatch, promotion.batch_pk)
        target_site = detached_site(session.get(Site, batch.target_site_pk))
        snapshot = (
            promotion.pk,
            batch.target_title,
            promotion.body,
            promotion.comment,
            promotion.intent,
        )
        status = promotion.status
        batch_status = batch.status

    if status is not PromotionStatus.staged:
        raise PromotionError(
            f"promotion {promotion_pk} is {status.value}; only a staged row runs"
        )

    if batch_status not in (BatchStatus.draft, BatchStatus.running):
        raise PromotionError(
            f"batch {promotion.batch_pk} is {batch_status.value}; it cannot push"
        )

    guard = _preflight(session, promotion_pk, force=force)

    if guard is not None:
        return guard

    _, title, body, comment, intent = snapshot
    current = session.get(Promotion, promotion_pk)
    base_revid = _effective_base_revid(session, current)
    pre_push = target_head_revid(session, current)

    try:
        client = client_factory(target_site)
        if intent is PromotionIntent.create:
            result = client.create_page(
                title,
                body,
                comment,
                force=force,
            )
        else:
            result = client.save_page(
                title,
                body,
                base_revid,
                comment,
                force=force,
            )
    except EditConflict as exc:
        return _record(
            session,
            promotion_pk,
            PromotionStatus.conflict,
            pre_push=pre_push,
            error=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - a refusal is a status, not a crash
        log.warning("promotion %s failed to push %s: %s", promotion_pk, title, exc)
        return _record(
            session,
            promotion_pk,
            PromotionStatus.error,
            pre_push=pre_push,
            error=str(exc),
        )

    return _record(
        session,
        promotion_pk,
        PromotionStatus.pushed,
        pre_push=pre_push,
        result_revid=getattr(result, "revid", None),
    )


def _preflight(session: Session, promotion_pk: int, *, force: bool) -> Promotion | None:
    """The checks that can be answered without asking the wiki.

    Returns a settled promotion when one of them decides the outcome, or None
    to go ahead. Answering locally where we can turns a network round trip into
    a row update, and gives the row a reason a person can read.
    """
    with read_snapshot(session):
        promotion = session.get(Promotion, promotion_pk)
        expected_base = _effective_base_revid(session, promotion)
        actual_base = target_head_revid(session, promotion)
        stale_source = not source_is_unchanged(session, promotion)
        already_there = body_matches_target(session, promotion)

    if stale_source and not force:
        return _record(
            session,
            promotion_pk,
            PromotionStatus.conflict,
            error=(
                "the source has moved since this was staged, so the frozen "
                "body is no longer what it claims to be. Re-stage from a fresh "
                "report."
            ),
        )
    if already_there:
        # Not an error and not a push: writing it would append a revision that
        # changes nothing, on somebody's watchlist.
        return _record(
            session,
            promotion_pk,
            PromotionStatus.skipped,
            result_revid=actual_base,
            error="the target already holds this exact body",
        )
    target_moved = (
        actual_base is not None
        if promotion.intent is PromotionIntent.create
        else actual_base != expected_base
    )
    if target_moved and not force:
        return _record(
            session,
            promotion_pk,
            PromotionStatus.conflict,
            pre_push=actual_base,
            error=(
                "the target has moved since this change was reviewed "
                f"(expected {expected_base}, found {actual_base})"
            ),
        )
    return None


def _effective_base_revid(session: Session, promotion: Promotion) -> int | None:
    """Resolve the real target base for this ordered revision step."""
    if promotion.predecessor_promotion_pk is None:
        return promotion.base_revid
    predecessor = session.get(Promotion, promotion.predecessor_promotion_pk)
    if predecessor is None:  # pragma: no cover - FK holds
        raise PromotionError(
            f"promotion {promotion.pk} has no predecessor "
            f"{promotion.predecessor_promotion_pk}"
        )
    if (
        predecessor.status
        not in (
            PromotionStatus.pushed,
            PromotionStatus.skipped,
        )
        or predecessor.result_revid is None
    ):
        raise PromotionError(
            f"promotion {promotion.pk} follows promotion {predecessor.pk}; "
            "push that revision successfully first"
        )
    return predecessor.result_revid


def _record(
    session: Session,
    promotion_pk: int,
    status: PromotionStatus,
    *,
    pre_push: int | None = None,
    result_revid: int | None = None,
    error: str | None = None,
) -> Promotion:
    with write_batch(session):
        promotion = session.get(Promotion, promotion_pk)
        promotion.status = status
        promotion.error_message = error
        if pre_push is not None:
            promotion.pre_push_target_revid = pre_push
        if result_revid is not None:
            promotion.result_revid = result_revid
        if status is not PromotionStatus.skipped:
            promotion.pushed_at = utcnow()
        session.add(promotion)
        if status is PromotionStatus.pushed:
            _enqueue_chain_refetch(session, promotion)
        elif status in (PromotionStatus.conflict, PromotionStatus.error):
            successor = session.exec(
                select(Promotion).where(
                    Promotion.predecessor_promotion_pk == promotion.pk,
                    Promotion.status == PromotionStatus.staged,
                )
            ).first()
            if successor is not None:
                skip(session, successor)
        batch = session.get(PromotionBatch, promotion.batch_pk)
        settle_batch(session, batch)

    with read_snapshot(session):
        return session.get(Promotion, promotion_pk)


def _enqueue_chain_refetch(session: Session, promotion: Promotion) -> None:
    """Fetch a completed target chain so its exact ladder rungs can be stored."""
    successor = session.exec(
        select(Promotion).where(Promotion.predecessor_promotion_pk == promotion.pk)
    ).first()
    if successor is not None:
        return
    chain_size = len(
        session.exec(
            select(Promotion).where(Promotion.batch_pk == promotion.batch_pk)
        ).all()
    )
    batch = session.get(PromotionBatch, promotion.batch_pk)
    session.add(
        FetchRequest(
            site_pk=batch.target_site_pk,
            title=batch.target_title,
            kind=FetchKind.single,
            depth=0,
            revisions=max(1, chain_size),
            priority=10,
        )
    )
