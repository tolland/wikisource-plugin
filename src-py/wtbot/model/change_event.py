from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from wtbot.timeutil import utcnow

"""The change feed: an append-only log of things that happened, for watchers.

Workers (the in-process drain, ``wtbot drain`` in its own process, the
background drain behind the viewer) record what they did here, in the same
transaction as the work itself. The websocket in ``wtbot.api.events`` tails the
table. The table is the transport on purpose: a CLI drain is a separate OS
process and cannot call into the server's memory, and a worker that dialled the
socket itself would lose its report exactly when the connection -- the
unreliable part -- was down. A row is written whether or not anyone is watching,
and a viewer that connects late, or reconnects, asks for ``after=<last pk>`` and
misses nothing.

Rows reference sites and requests by plain integer, not foreign key: this is a
log, and deleting a site or a fetch request must not be blocked by (or erase)
the record that it happened.
"""


class EventTopic(str, Enum):
    fetch = "fetch"
    drain = "drain"


class EventKind(str, Enum):
    queued = "queued"
    done = "done"
    failed = "failed"
    retried = "retried"
    cancelled = "cancelled"
    drain_started = "drain_started"
    drain_finished = "drain_finished"


class EventLevel(str, Enum):
    info = "info"
    warning = "warning"
    error = "error"


class ChangeEvent(SQLModel, table=True):
    pk: int | None = Field(default=None, primary_key=True)
    at: datetime = Field(default_factory=utcnow, index=True)
    topic: EventTopic = Field(index=True)
    kind: EventKind
    level: EventLevel = EventLevel.info

    site_pk: int | None = None
    request_pk: int | None = Field(default=None, index=True)
    title: str | None = None

    message: str | None = None
    """One line a person can read in a feed."""

    failure_kind: str | None = None
    """``FailureKind`` value for a failed fetch (rate_limited, auth, ...)."""
    http_status: int | None = None
    retry_after: float | None = None
    detail: str | None = None
    """Long form -- traceback tail -- kept out of ``message`` so a feed row stays
    one line and the full account is one click away."""
