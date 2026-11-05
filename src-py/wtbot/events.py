import logging

from sqlmodel import Session, select

from wtbot.db_session import write_batch
from wtbot.model import ChangeEvent, EventKind, EventLevel, EventTopic

"""Writing to the change feed (see ``wtbot.model.change_event``).

Two entry points, because workers are in two situations:

``add_event``     inside a transaction the caller already owns (``write_batch``).
                  The event commits or rolls back with the work it describes, so
                  the feed can never claim a result the database does not hold.
``record_event``  standalone, for things that happen outside a transaction
                  (a drain starting, a request being queued by an endpoint).

Neither may be able to fail the work it reports on, so ``record_event`` swallows
its own errors; ``add_event`` cannot fail except by failing the caller's commit,
which is the point.
"""

MESSAGE_LIMIT = 300
DETAIL_LIMIT = 6000


def add_event(
    session: Session,
    topic: EventTopic,
    kind: EventKind,
    *,
    level: EventLevel = EventLevel.info,
    site_pk: int | None = None,
    request_pk: int | None = None,
    title: str | None = None,
    message: str | None = None,
    failure_kind: str | None = None,
    http_status: int | None = None,
    retry_after: float | None = None,
    detail: str | None = None,
) -> ChangeEvent:
    event = ChangeEvent(
        topic=topic,
        kind=kind,
        level=level,
        site_pk=site_pk,
        request_pk=request_pk,
        title=title,
        message=None if message is None else message[:MESSAGE_LIMIT],
        failure_kind=failure_kind,
        http_status=http_status,
        retry_after=retry_after,
        # The tail, not the head: the exception is at the bottom of a traceback.
        detail=None if detail is None else detail[-DETAIL_LIMIT:],
    )
    session.add(event)
    return event


def record_event(
    session: Session, topic: EventTopic, kind: EventKind, **fields
) -> None:
    """Append an event in its own transaction. Never raises."""
    try:
        with write_batch(session):
            add_event(session, topic, kind, **fields)
    except Exception:  # noqa: BLE001 - reporting must not break the work
        logging.getLogger(__name__).debug("recording event failed", exc_info=True)


def latest_event_pk(session: Session) -> int:
    try:
        return (
            session.exec(select(ChangeEvent.pk).order_by(ChangeEvent.pk.desc())).first()
            or 0
        )
    finally:
        session.rollback()


def events_after(
    session: Session,
    after: int,
    *,
    topic: EventTopic | None = None,
    limit: int = 500,
) -> list[ChangeEvent]:
    """Events with pk > ``after``, oldest first -- the tail a watcher reads."""
    query = select(ChangeEvent).where(ChangeEvent.pk > after)
    if topic is not None:
        query = query.where(ChangeEvent.topic == topic)
    return _detached(session, query.order_by(ChangeEvent.pk).limit(limit))


def recent_events(
    session: Session, *, topic: EventTopic | None = None, limit: int = 50
) -> list[ChangeEvent]:
    """The newest ``limit`` events, returned oldest first."""
    query = select(ChangeEvent)
    if topic is not None:
        query = query.where(ChangeEvent.topic == topic)
    rows = _detached(session, query.order_by(ChangeEvent.pk.desc()).limit(limit))
    return list(reversed(rows))


def _detached(session: Session, query) -> list[ChangeEvent]:  # noqa: ANN001
    """Run a read and leave the session idle, keeping the rows usable.

    Expunged before the rollback: a rollback expires attached instances, and a
    feed row is read after the session is gone (serialised, or sent on a socket).
    """
    try:
        rows = list(session.exec(query).all())
        for row in rows:
            session.expunge(row)
        return rows
    finally:
        session.rollback()
