import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlmodel import Session
from starlette.concurrency import run_in_threadpool

from wtbot.deps import get_session
from wtbot.events import events_after, recent_events
from wtbot.fetch.queue_runner import QueueStats, queue_stats
from wtbot.model import ChangeEvent, EventTopic, FetchStatus

"""The change feed, over REST and websocket.

``GET /events`` is the same feed for scripts and for catching up. ``WS
/events/ws`` is the live view: it replays from ``after`` (or the last few
events), then tails the table. Tailing the table, rather than being pushed to by
workers, is what lets a ``wtbot drain`` running in another process show up in
the viewer -- see ``wtbot.model.change_event``.

A reconnecting client passes ``after=<pk of the last event it saw>`` and gets
exactly what it missed, so the connection can be as flaky as it likes.
"""

log = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])

POLL_SECONDS = 0.5
BACKLOG = 50


class EventFrame(BaseModel):
    type: Literal["event"] = "event"
    event: ChangeEvent


class QueueFrame(BaseModel):
    """Queue depth, sent when it changes, so counters need no polling."""

    type: Literal["queue"] = "queue"
    counts: dict[FetchStatus, int]
    pending: int
    total: int


class EventList(BaseModel):
    events: list[ChangeEvent]


@router.get("", response_model=EventList)
def list_events(
    after: int | None = Query(
        default=None, description="Only events with a larger pk."
    ),
    topic: EventTopic | None = None,
    limit: int = Query(default=BACKLOG, ge=1, le=500),
    session: Session = Depends(get_session),
) -> EventList:
    """Oldest-first. Without ``after``, the newest ``limit`` events."""
    if after is None:
        return EventList(events=recent_events(session, topic=topic, limit=limit))
    return EventList(events=events_after(session, after, topic=topic, limit=limit))


def _queue_frame(stats: QueueStats) -> QueueFrame:
    return QueueFrame(counts=stats.counts, pending=stats.pending, total=stats.total)


@router.websocket("/ws")
async def events_ws(
    websocket: WebSocket, after: int | None = None, topic: EventTopic | None = None
) -> None:
    await websocket.accept()
    engine = websocket.app.state.engine

    def read(last: int | None) -> tuple[list[ChangeEvent], QueueStats]:
        with Session(engine) as session:
            if last is None:
                events = recent_events(session, topic=topic, limit=BACKLOG)
            else:
                events = events_after(session, last, topic=topic)
            return events, queue_stats(session)

    last = after
    sent_stats: QueueFrame | None = None
    try:
        while True:
            events, stats = await run_in_threadpool(read, last)
            for event in events:
                assert event.pk is not None
                last = event.pk
                await websocket.send_text(EventFrame(event=event).model_dump_json())
            if last is None:
                last = 0  # empty feed: tail from the start
            frame = _queue_frame(stats)
            if frame != sent_stats:
                sent_stats = frame
                await websocket.send_text(frame.model_dump_json())
            # Wait for the next poll, but notice the client leaving promptly.
            try:
                message = await asyncio.wait_for(websocket.receive(), POLL_SECONDS)
            except TimeoutError:
                continue
            if message["type"] == "websocket.disconnect":
                return
    except WebSocketDisconnect:
        return
    except RuntimeError:
        # Starlette raises this when sending after the peer closed.
        return
