import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from sqlmodel import Session, func, select

from wtbot.model import FetchRequest, FetchStatus
from wtbot.worker import ClientFactory, run_pending

"""Draining the fetch queue.

``run_pending`` is the primitive: claim up to N requests and process them.
Draining is the *policy* built on it -- keep going until the queue is empty --
and it has to be a policy rather than a loop copied into each caller, because
one pass is never enough: an ``Index:`` fetch fans out into hundreds of
``Page:`` children that did not exist when the pass began.

Three call sites used to spell this out as ``while run_pending(...) > 0: pass``,
inline in the request handler that enqueued the work. That coupling is what
made the upstream rate limiting so painful: enqueueing a book meant holding one
HTTP request open for every page of it, and the correct fix for rate limiting
-- slowing down -- makes that wait longer, not shorter. Enqueue and drain are
separate operations now (``POST /fetch`` and ``POST /fetch/drain``), so the
throttle can be as slow as the wiki demands without any caller timing out.
"""

log = logging.getLogger(__name__)

#: Requests claimed per pass. Each pass is one transaction's worth of claiming;
#: the loop below repeats until nothing is left.
DEFAULT_BATCH = 200

#: A fan-out enqueues children, so several passes are normal. This bound exists
#: only so a pathological cycle cannot spin forever inside one HTTP request.
DEFAULT_MAX_PASSES = 100


class DrainStop(str, Enum):
    """Why the drain returned. A caller that cannot tell an empty queue from an
    abandoned one cannot tell "the book is fetched" from "stopped early"."""

    queue_empty = "queue_empty"
    max_passes = "max_passes"


@dataclass(frozen=True)
class DrainResult:
    handled: int
    passes: int
    remaining: int  # still pending/in-progress when the drain returned
    stop_reason: DrainStop

    @property
    def complete(self) -> bool:
        return self.stop_reason is DrainStop.queue_empty and self.remaining == 0


@dataclass(frozen=True)
class QueueStats:
    """A snapshot of the queue, for the CLI and for progress display."""

    counts: dict[FetchStatus, int]
    oldest_pending_at: datetime | None

    @property
    def pending(self) -> int:
        return self.counts.get(FetchStatus.pending, 0)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def drain_queue(
    session: Session,
    client_factory: ClientFactory,
    *,
    blob_root: Path | None = None,
    batch: int = DEFAULT_BATCH,
    max_passes: int | None = DEFAULT_MAX_PASSES,
) -> DrainResult:
    """Process pending fetch requests until the queue is empty.

    Every wiki call this makes is throttled (see wtbot.wiki.config), so a large
    fan-out takes minutes by design. Nothing here is on a request path that
    must answer quickly.
    """
    handled = 0
    passes = 0
    stop = DrainStop.queue_empty

    while True:
        if max_passes is not None and passes >= max_passes:
            stop = DrainStop.max_passes
            log.warning(
                "drain stopped after %d passes with %d requests still queued; "
                "a fan-out cycle is the usual cause",
                passes,
                pending_count(session),
            )
            break
        done = run_pending(session, client_factory, blob_root=blob_root, limit=batch)
        passes += 1
        handled += done
        if done == 0:
            break

    result = DrainResult(
        handled=handled,
        passes=passes,
        remaining=pending_count(session),
        stop_reason=stop,
    )
    if handled:
        log.info(
            "drained %d fetch requests in %d passes (%d remaining)",
            result.handled,
            result.passes,
            result.remaining,
        )
    return result


def pending_count(session: Session) -> int:
    """Requests that a further drain would pick up. ``in_progress`` counts:
    a row left there by a crashed run is unfinished work, not finished work."""
    try:
        return int(
            session.exec(
                select(func.count())
                .select_from(FetchRequest)
                .where(
                    FetchRequest.status.in_(
                        (FetchStatus.pending, FetchStatus.in_progress)
                    )
                )
            ).one()
        )
    finally:
        session.rollback()


def queue_stats(session: Session) -> QueueStats:
    try:
        rows = session.exec(
            select(FetchRequest.status, func.count()).group_by(FetchRequest.status)
        ).all()
        oldest = session.exec(
            select(func.min(FetchRequest.requested_at)).where(
                FetchRequest.status == FetchStatus.pending
            )
        ).one()
        return QueueStats(
            counts={FetchStatus(status): int(count) for status, count in rows},
            oldest_pending_at=oldest,
        )
    finally:
        session.rollback()
