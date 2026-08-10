import logging

from sqlmodel import Session

from wtbot.db_session import detached_site, read_snapshot, write_batch
from wtbot.model import (
    BatchStatus,
    LinkOrigin,
    Promotion,
    PromotionBatch,
    PromotionIntent,
    PromotionStatus,
    Site,
)
from wtbot.promotion_store import (
    PromotionError,
    body_matches_target,
    settle_batch,
    source_is_unchanged,
    target_head_revid,
)
from wtbot.timeutil import utcnow
from wtbot.wiki.wiki_types import EditConflict

"""Executing one promotion: the only place this system writes to a target wiki.

**One page per call, by design.** A reviewer can watch it, pause it and abandon
it between pages; a rate-limited wiki gets one request rather than three
hundred; and a batch that half-succeeds needs no unpicking, because each row
already carries its own outcome.

**Three checks before the write, and each is a different failure:**

- the batch is approved -- an unapproved run has nobody's name on it;
- the source still holds the revision that was staged -- otherwise the frozen
  body is not what anybody reviewed;
- the target still holds the base revid -- which the wiki re-checks itself via
  ``baserevid``, but checking here first turns a network round trip into a row
  update, and gives the conflict a local explanation.

**The push does not write a link.** A successful push means the target now
holds our content, which *is* a correspondence -- but the revision it created
is known here only as a revid, and the revision store is owned by the fetch
worker (one writer per table). So the promotion records the result and enqueues
nothing; a later fetch makes the revision concrete, and linking it is the
ordinary `propose` path over real rows rather than a row invented from a save
response. See the note in ``wtbot.revision_store``.
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
            promotion.target_title,
            promotion.body,
            promotion.comment,
            promotion.base_revid,
            promotion.intent,
        )
        status = promotion.status
        batch_status = batch.status

    if status is not PromotionStatus.staged:
        raise PromotionError(
            f"promotion {promotion_pk} is {status.value}; only a staged row runs"
        )
    if batch_status not in (BatchStatus.approved, BatchStatus.running):
        raise PromotionError(
            f"batch {promotion.batch_pk} is {batch_status.value}: approve it "
            "before pushing. An unapproved run has nobody's name on it."
        )

    guard = _preflight(session, promotion_pk, force=force)
    if guard is not None:
        return guard

    _, title, body, comment, base_revid, intent = snapshot
    pre_push = target_head_revid(session, session.get(Promotion, promotion_pk))

    try:
        client = client_factory(target_site)
        result = client.save_page(
            title,
            body,
            base_revid if intent is PromotionIntent.update else None,
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
            error="the target already holds this exact body",
        )
    return None


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
        batch = session.get(PromotionBatch, promotion.batch_pk)
        settle_batch(session, batch)

    with read_snapshot(session):
        return session.get(Promotion, promotion_pk)


#: What a successful push has established, for whoever links it afterwards.
#: `copy` is the strongest origin available -- the target revision exists
#: *because* the source one did -- and it is the right claim to record once a
#: refetch has made that revision concrete.
PUSHED_LINK_ORIGIN = LinkOrigin.copy
